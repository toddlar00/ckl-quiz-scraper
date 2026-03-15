#!/usr/bin/env python3
"""CKL Quiz Scraper — scrape quizzes from coreknowledgeforlawyers.com.

Navigates Practice Sets → Chapters → Questions, submitting each question
to capture the correct answer and explanation. Exports to multiple formats
including JSON, CSV, Anki, Quizlet, Kahoot, and Moodle.
"""

import argparse
import logging
import sys
import time

from scraper.browser import create_driver, diagnose_page, login
from scraper.exporters import ALL_FORMATS, export_all
from scraper.quiz_scraper import (
    Chapter,
    PracticeSet,
    clear_progress,
    discover_chapters,
    discover_practice_sets,
    scrape_chapter_questions,
)


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
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

examples:
  %(prog)s                                       # scrape everything, all formats
  %(prog)s --practice-set "Civil Procedure"      # one practice set
  %(prog)s --chapter "Subject Matter"            # filter by chapter name
  %(prog)s --format json csv anki                # specific export formats
  %(prog)s --chapter-url URL                     # scrape one chapter directly
  %(prog)s --fresh                               # ignore previous progress
  %(prog)s --no-headless -v                      # debug mode (visible browser)
""",
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
        help="Delay in seconds between questions (default: 1.0)",
    )
    behavior.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Apply runtime config overrides
    import scraper.config as cfg
    if args.no_headless:
        cfg.HEADLESS = False
    if args.delay is not None:
        cfg.REQUEST_DELAY = args.delay
    if args.fresh:
        clear_progress()

    driver = None
    start_time = time.time()
    try:
        logger.info("Starting CKL Quiz Scraper...")
        driver = create_driver()

        # Login
        if not args.skip_login:
            logger.info("Logging in...")
            success = login(driver)
            if not success:
                logger.error(
                    "Login failed. Troubleshooting steps:\n"
                    "  1. Check CKL_USERNAME and CKL_PASSWORD in your .env file\n"
                    "  2. Run with --no-headless to watch the browser\n"
                    "  3. Check debug_screenshots/ for captured page state\n"
                    "  4. Ensure the site is accessible: %s", cfg.BASE_URL,
                )
                sys.exit(1)
            logger.info("Login successful!")

        all_practice_sets = []

        # Direct chapter URL mode
        if args.chapter_url:
            chapter = Chapter(
                chapter_name="Direct Chapter",
                launch_url=args.chapter_url,
            )
            logger.info("Scraping chapter: %s", args.chapter_url)
            scrape_chapter_questions(driver, chapter, resume=not args.fresh)

            ps = PracticeSet(
                title="Direct Scrape",
                url=args.chapter_url,
                chapters=[chapter],
            )
            all_practice_sets.append(ps)

        else:
            # Discover practice sets
            logger.info("Discovering practice sets...")
            ps_links = discover_practice_sets(driver)

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

                chapters = discover_chapters(driver, ps_url)
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

                for i, chapter in enumerate(chapters, 1):
                    logger.info(
                        "----- Chapter %d/%d: %s -----",
                        i, len(chapters), chapter.chapter_name,
                    )
                    scrape_chapter_questions(driver, chapter, resume=not args.fresh)
                    logger.info(
                        "  Result: %d question(s) scraped",
                        len(chapter.questions),
                    )

                all_practice_sets.append(ps)

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

        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info("=" * 60)
        logger.info("  Practice sets: %d", len(all_practice_sets))
        logger.info("  Chapters:      %d", total_chapters)
        logger.info("  Questions:     %d", total_questions)
        logger.info("  Time elapsed:  %.0f seconds", elapsed)

        formats = args.format  # None means all
        logger.info("Exporting to: %s", ", ".join(formats or ALL_FORMATS))
        paths = export_all(all_practice_sets, args.output_dir, formats)

        logger.info("Export complete! Files saved:")
        for fmt, path in paths.items():
            logger.info("  %-12s %s", fmt + ":", path)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user. Progress has been saved.")
        logger.info("Run again to resume from where you left off.")
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
