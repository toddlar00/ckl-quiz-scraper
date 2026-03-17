#!/usr/bin/env python3
"""CKL Quiz Scraper — scrape quizzes from coreknowledgeforlawyers.com.

Navigates Practice Sets → Chapters → Questions, submitting each question
to capture the correct answer and explanation. Exports to multiple formats
including JSON, CSV, Anki, Quizlet, Kahoot, Moodle, and Canvas QTI.
"""

import argparse
import logging
import os
import sys
import time

from scraper.browser import create_driver, diagnose_page, login
from scraper.exporters import ALL_FORMATS, export_all
from scraper.models import Chapter, PracticeSet, validate_practice_sets
from scraper.adaptive_delay import AdaptiveDelay, get_adaptive_delay, reset_adaptive_delay
from scraper.progress import clear_progress
from scraper.shutdown import install_signal_handlers, shutdown_requested
from scraper.quiz_scraper import (
    discover_chapters,
    discover_practice_sets,
    scrape_chapter_questions,
)
from scraper.sites import DEFAULT_SITE, SITE_SCRAPERS


def setup_logging(verbose=False, log_file=None):
    """Configure logging to console and optionally to a file."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )
    # Suppress noisy third-party loggers
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("WDM").setLevel(logging.WARNING)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape quiz questions, answers, and explanations from CKL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
export formats:
  json         Structured JSON (default)
  csv          Flat CSV, one row per question (default)
  anki         Tab-separated file for Anki flashcard import
  quizlet      Tab-separated file for Quizlet import
  kahoot       CSV matching Kahoot spreadsheet template
  moodle_gift  Moodle GIFT plain-text format
  moodle_xml   Moodle XML format with categories and feedback
  canvas_qti   Canvas LMS QTI 1.2 package (.zip)

examples:
  %(prog)s                                       # scrape everything, all formats
  %(prog)s --practice-set "Civil Procedure"      # one practice set
  %(prog)s --chapter "Subject Matter"            # filter by chapter name
  %(prog)s --format json csv anki                # specific export formats
  %(prog)s --chapter-url URL                     # scrape one chapter directly
  %(prog)s --fresh                               # ignore previous progress
  %(prog)s --mc-only                              # only record multiple-choice questions
  %(prog)s --no-headless -v                      # debug mode (visible browser)
  %(prog)s --dry-run                             # preview what would be scraped
  %(prog)s --log-file scrape.log                 # save log output to file
  %(prog)s --site ckl                            # select quiz site (default: ckl)
""",
    )

    # Site selection
    site_names = list(SITE_SCRAPERS.keys())
    parser.add_argument(
        "--site",
        choices=site_names,
        default=DEFAULT_SITE,
        help=f"Quiz site to scrape (default: {DEFAULT_SITE}). Available: {', '.join(site_names)}",
    )

    # Scraping scope
    scope = parser.add_argument_group("scraping scope")
    scope.add_argument(
        "--practice-set",
        help="Scrape only practice sets matching this substring",
    )
    scope.add_argument(
        "--chapter",
        help="Scrape only chapters matching this substring",
    )
    scope.add_argument(
        "--chapter-url",
        help="Directly scrape a specific chapter launch URL (skip discovery)",
    )

    # Export
    export = parser.add_argument_group("export options")
    export.add_argument(
        "--format", "-f",
        nargs="+",
        choices=ALL_FORMATS,
        default=None,
        metavar="FMT",
        help=f"Export formats (default: all). Choices: {', '.join(ALL_FORMATS)}",
    )
    export.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Output directory (default: output)",
    )

    # Behavior
    behavior = parser.add_argument_group("behavior")
    behavior.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser visibly (useful for debugging)",
    )
    behavior.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip the login step (use with saved cookies)",
    )
    behavior.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore saved progress and re-scrape everything",
    )
    behavior.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Fixed delay in seconds between questions (disables adaptive mode)",
    )
    behavior.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    behavior.add_argument(
        "--mc-only",
        action="store_true",
        help="Only record multiple-choice questions (skip fill-in, essay, select-all, etc.)",
    )
    behavior.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover practice sets and chapters without scraping questions",
    )
    behavior.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Also write log output to a file",
    )

    args = parser.parse_args()
    setup_logging(args.verbose, args.log_file)
    logger = logging.getLogger(__name__)

    # Apply runtime config overrides
    import scraper.config as cfg
    if args.no_headless:
        cfg.HEADLESS = False
    if args.delay is not None:
        cfg.REQUEST_DELAY = args.delay
        # Fixed delay mode: set the adaptive delay to a fixed budget
        # based on the user's specified delay (scaled up to full budget)
        import scraper.adaptive_delay as ad_mod
        fixed = AdaptiveDelay(initial_budget=args.delay * 9.0)
        # Override on_success/on_failure to be no-ops (fixed mode)
        fixed.on_success = lambda: None
        fixed.on_failure = lambda: None
        ad_mod._adaptive_delay = fixed
    if args.fresh:
        clear_progress()
        reset_adaptive_delay()

    driver = None
    all_practice_sets = []
    start_time = time.time()

    # Install graceful shutdown handlers (Ctrl+C saves progress + exports partial data)
    install_signal_handlers()

    try:
        scraper_cls = SITE_SCRAPERS[args.site]
        logger.info("Starting %s scraper...", scraper_cls.SITE_NAME)
        driver = create_driver()
        site = scraper_cls(driver)
        site.mc_only = args.mc_only

        # Login
        if not args.skip_login:
            logger.info("Logging in...")
            # Select credentials based on site
            if args.site == "westacademic":
                username = cfg.WA_USERNAME or cfg.USERNAME
                password = cfg.WA_PASSWORD or cfg.PASSWORD
                cred_hint = "WA_USERNAME/WA_PASSWORD (or CKL_USERNAME/CKL_PASSWORD)"
            else:
                username = cfg.USERNAME
                password = cfg.PASSWORD
                cred_hint = "CKL_USERNAME/CKL_PASSWORD"

            success = site.login(username, password)
            if not success:
                logger.error(
                    "Login failed. Troubleshooting steps:\n"
                    "  1. Check %s in your .env file\n"
                    "  2. Run with --no-headless to watch the browser\n"
                    "  3. Check debug_screenshots/ for captured page state\n"
                    "  4. Ensure the site is accessible: %s",
                    cred_hint, scraper_cls.BASE_URL,
                )
                sys.exit(1)
            logger.info("Login successful!")

        # Direct chapter URL mode
        if args.chapter_url:
            if args.dry_run:
                logger.info("[DRY RUN] Would scrape chapter: %s", args.chapter_url)
                return

            chapter = Chapter(
                chapter_name="Direct Chapter",
                launch_url=args.chapter_url,
            )
            logger.info("Scraping chapter: %s", args.chapter_url)
            site.scrape_chapter(chapter, resume=not args.fresh)

            ps = PracticeSet(
                title="Direct Scrape",
                url=args.chapter_url,
                chapters=[chapter],
            )
            all_practice_sets.append(ps)

        else:
            # Discover practice sets
            logger.info("Discovering practice sets...")
            ps_links = site.discover_practice_sets()

            if not ps_links:
                logger.error(
                    "No practice sets found. Troubleshooting steps:\n"
                    "  1. Run with --no-headless -v to inspect the page\n"
                    "  2. Check debug_screenshots/ for captured page state\n"
                    "  3. Verify your account has practice sets assigned"
                )
                sys.exit(1)

            # Filter by practice set name
            if args.practice_set:
                ps_links = [
                    (t, u) for t, u in ps_links
                    if args.practice_set.lower() in t.lower()
                ]
                if not ps_links:
                    logger.error(
                        "No practice set matching '%s'. Run without "
                        "--practice-set to see available sets.",
                        args.practice_set,
                    )
                    sys.exit(1)
                logger.info(
                    "Filtered to %d practice set(s) matching '%s'",
                    len(ps_links), args.practice_set,
                )

            for ps_title, ps_url in ps_links:
                logger.info("=" * 60)
                logger.info("Practice Set: %s", ps_title)
                logger.info("=" * 60)

                chapters = site.discover_chapters(ps_url)
                if not chapters:
                    logger.warning("  No chapters found, skipping")
                    continue

                # Filter chapters
                if args.chapter:
                    chapters = [
                        ch for ch in chapters
                        if args.chapter.lower() in ch.chapter_name.lower()
                    ]
                    if not chapters:
                        logger.info(
                            "  No chapters matching '%s', skipping",
                            args.chapter,
                        )
                        continue
                    logger.info(
                        "  Filtered to %d chapter(s) matching '%s'",
                        len(chapters), args.chapter,
                    )

                ps = PracticeSet(title=ps_title, url=ps_url, chapters=chapters)

                if args.dry_run:
                    logger.info("[DRY RUN] Would scrape %d chapter(s):", len(chapters))
                    for ch in chapters:
                        logger.info("  - %s [%s]", ch.chapter_name, ch.status)
                else:
                    for i, chapter in enumerate(chapters, 1):
                        if shutdown_requested():
                            logger.info("Shutdown requested — stopping after current practice set")
                            break
                        logger.info(
                            "----- Chapter %d/%d: %s -----",
                            i, len(chapters), chapter.chapter_name,
                        )
                        site.scrape_chapter(chapter, resume=not args.fresh)
                        logger.info(
                            "  Result: %d question(s) scraped",
                            len(chapter.questions),
                        )

                all_practice_sets.append(ps)
                if shutdown_requested():
                    break

            if args.dry_run:
                total_chapters = sum(len(ps.chapters) for ps in all_practice_sets)
                elapsed = time.time() - start_time
                logger.info("=" * 60)
                logger.info("DRY RUN SUMMARY")
                logger.info("=" * 60)
                logger.info("  Practice sets: %d", len(all_practice_sets))
                logger.info("  Chapters:      %d", total_chapters)
                logger.info("  Time elapsed:  %.0f seconds", elapsed)
                logger.info("Run without --dry-run to scrape questions.")
                return

        # Validate extracted data
        warning_count = validate_practice_sets(all_practice_sets)
        if warning_count:
            logger.info("Data validation: %d warning(s) found (see above)", warning_count)

        # Export results
        total_questions = sum(
            len(ch.questions)
            for ps in all_practice_sets
            for ch in ps.chapters
        )

        if total_questions == 0:
            logger.warning(
                "No questions were scraped. Troubleshooting steps:\n"
                "  1. Check if chapters were skipped (already completed).\n"
                "     Use --fresh to re-scrape everything.\n"
                "  2. Run with --no-headless -v to watch the scraping process\n"
                "  3. Check debug_screenshots/ for captured page state"
            )
            sys.exit(1)

        total_chapters = sum(len(ps.chapters) for ps in all_practice_sets)
        elapsed = time.time() - start_time

        # Detailed summary statistics
        question_types = {}
        chapters_with_explanations = 0
        total_with_explanations = 0
        for ps in all_practice_sets:
            for ch in ps.chapters:
                ch_has_explanations = False
                for q in ch.questions:
                    qt = q.question_type or "Unknown"
                    question_types[qt] = question_types.get(qt, 0) + 1
                    if q.explanation:
                        total_with_explanations += 1
                        ch_has_explanations = True
                if ch_has_explanations:
                    chapters_with_explanations += 1

        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info("  Practice sets: %d", len(all_practice_sets))
        logger.info("  Chapters:      %d", total_chapters)
        logger.info("  Questions:     %d", total_questions)
        logger.info("  Time elapsed:  %.0f seconds", elapsed)
        if total_questions > 0:
            rate = elapsed / total_questions
            logger.info("  Avg time/question: %.1f seconds", rate)
        logger.info("  With explanations: %d/%d (%.0f%%)",
                     total_with_explanations, total_questions,
                     (total_with_explanations / total_questions * 100) if total_questions else 0)
        if question_types:
            logger.info("  Question types:")
            for qt, count in sorted(question_types.items(), key=lambda x: -x[1]):
                logger.info("    %-25s %d", qt, count)
        adaptive_info = get_adaptive_delay().summary()
        logger.info("  Adaptive delay:    %.1fs (after %d adjustments)",
                     adaptive_info["current_budget"], adaptive_info["total_adjustments"])
        logger.info("  Per practice set:")
        for ps in all_practice_sets:
            ps_q = sum(len(ch.questions) for ch in ps.chapters)
            logger.info("    %-40s %d ch, %d q", ps.title[:40], len(ps.chapters), ps_q)

        formats = args.format  # None means all
        logger.info("Exporting to: %s", ", ".join(formats or ALL_FORMATS))
        paths = export_all(all_practice_sets, args.output_dir, formats)

        logger.info("Export complete! Files saved:")
        for fmt, path in paths.items():
            file_size = os.path.getsize(path) if os.path.exists(path) else 0
            if file_size < 1024:
                size_str = f"{file_size} B"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
            logger.info("  %-12s %s (%s)", fmt + ":", path, size_str)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user.")
        # Export whatever data was collected before exiting
        total_questions = sum(
            len(ch.questions)
            for ps in all_practice_sets
            for ch in ps.chapters
        )
        if total_questions > 0:
            logger.info("Exporting %d question(s) collected so far...", total_questions)
            try:
                formats = args.format
                paths = export_all(all_practice_sets, args.output_dir, formats)
                logger.info("Partial export complete! Files saved:")
                for fmt, path in paths.items():
                    logger.info("  %-12s %s", fmt + ":", path)
            except Exception as ex:
                logger.warning("Could not export partial results: %s", ex)
        logger.info("Progress has been saved. Run again to resume from where you left off.")
        sys.exit(130)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        if driver:
            diagnose_page(driver, "fatal_error")
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
            logger.debug("Browser closed")


if __name__ == "__main__":
    main()
