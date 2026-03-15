#!/usr/bin/env python3
"""CKL Quiz Scraper - Scrape quiz questions from coreknowledgeforlawyers.com.

Navigates through Practice Sets → Chapters → Questions, submitting each
question to reveal the correct answer and explanation.
"""

import argparse
import logging
import sys

from scraper.browser import create_driver, login
from scraper.exporter import export_all
from scraper.quiz_scraper import (
    Chapter,
    PracticeSet,
    discover_chapters,
    discover_practice_sets,
    scrape_chapter_questions,
)


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scrape quiz questions, answers, and explanations from CKL"
    )
    parser.add_argument(
        "--practice-set",
        help="Scrape only this practice set (by title substring match)",
    )
    parser.add_argument(
        "--chapter",
        help="Scrape only chapters matching this substring",
    )
    parser.add_argument(
        "--chapter-url",
        help="Directly scrape a specific chapter launch URL (skip discovery)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser visibly (useful for debugging)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip the login step",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    if args.no_headless:
        import scraper.config as cfg
        cfg.HEADLESS = False

    driver = None
    try:
        logger.info("Starting CKL Quiz Scraper...")
        driver = create_driver()

        # Login
        if not args.skip_login:
            logger.info("Logging in...")
            success = login(driver)
            if not success:
                logger.error(
                    "Login failed. Check your credentials in .env file. "
                    "Try --no-headless to debug visually."
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
            scrape_chapter_questions(driver, chapter)

            ps = PracticeSet(
                title="Direct Scrape",
                url=args.chapter_url,
                chapters=[chapter],
            )
            all_practice_sets.append(ps)

        else:
            # Discover practice sets from home page
            logger.info("Discovering practice sets...")
            ps_links = discover_practice_sets(driver)

            if not ps_links:
                logger.warning("No practice sets found on the home page.")
                sys.exit(1)

            # Filter by practice set name if specified
            if args.practice_set:
                ps_links = [
                    (t, u) for t, u in ps_links
                    if args.practice_set.lower() in t.lower()
                ]
                logger.info(
                    "Filtered to %d practice set(s) matching '%s'",
                    len(ps_links), args.practice_set,
                )

            for ps_title, ps_url in ps_links:
                logger.info("Opening practice set: %s", ps_title)

                chapters = discover_chapters(driver, ps_url)
                if not chapters:
                    logger.warning("  No chapters found, skipping")
                    continue

                # Filter chapters if specified
                if args.chapter:
                    chapters = [
                        ch for ch in chapters
                        if args.chapter.lower() in ch.chapter_name.lower()
                    ]
                    logger.info(
                        "  Filtered to %d chapter(s) matching '%s'",
                        len(chapters), args.chapter,
                    )

                ps = PracticeSet(
                    title=ps_title,
                    url=ps_url,
                    chapters=chapters,
                )

                for chapter in chapters:
                    logger.info("  Scraping: %s", chapter.chapter_name)
                    scrape_chapter_questions(driver, chapter)
                    logger.info(
                        "    -> %d question(s) scraped",
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
            logger.warning("No questions were scraped.")
            sys.exit(1)

        total_chapters = sum(len(ps.chapters) for ps in all_practice_sets)
        logger.info(
            "Exporting %d question(s) from %d chapter(s) across %d practice set(s)...",
            total_questions, total_chapters, len(all_practice_sets),
        )
        paths = export_all(all_practice_sets, args.output_dir)
        logger.info("Export complete!")
        logger.info("  JSON: %s", paths["json"])
        logger.info("  CSV:  %s", paths["csv"])

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if driver:
            driver.quit()
            logger.debug("Browser closed")


if __name__ == "__main__":
    main()
