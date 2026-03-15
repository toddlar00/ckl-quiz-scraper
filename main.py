#!/usr/bin/env python3
"""CKL Quiz Scraper - Scrape quiz questions from coreknowledgeforlawyers.com."""

import argparse
import logging
import sys

from scraper.browser import create_driver, login
from scraper.exporter import export_all
from scraper.quiz_scraper import discover_quiz_links, scrape_quiz


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Scrape quiz questions, answers, and explanations from Core Knowledge for Lawyers"
    )
    parser.add_argument(
        "--url",
        help="Specific quiz URL to scrape (skip auto-discovery)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Output directory for exported files (default: output)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (useful for debugging)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip the login step (if already authenticated via cookies)",
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
                    "You can also try --no-headless to debug visually."
                )
                sys.exit(1)
            logger.info("Login successful!")

        # Discover or use provided quiz URL
        if args.url:
            quiz_links = [("Custom Quiz", args.url)]
        else:
            logger.info("Discovering quiz pages...")
            quiz_links = discover_quiz_links(driver)

        if not quiz_links:
            logger.warning(
                "No quiz pages found. Try providing a specific URL with --url"
            )
            sys.exit(1)

        logger.info("Found %d quiz(zes) to scrape", len(quiz_links))

        # Scrape each quiz
        all_quizzes = []
        for title, url in quiz_links:
            logger.info("Scraping: %s (%s)", title, url)
            quiz = scrape_quiz(driver, url, title)
            if quiz.questions:
                all_quizzes.append(quiz)
                logger.info("  -> %d question(s) found", len(quiz.questions))
            else:
                logger.warning("  -> No questions found on this page")

        if not all_quizzes:
            logger.warning("No questions were scraped from any quiz page.")
            sys.exit(1)

        # Export results
        total_questions = sum(len(q.questions) for q in all_quizzes)
        logger.info(
            "Exporting %d question(s) from %d quiz(zes)...",
            total_questions, len(all_quizzes)
        )
        paths = export_all(all_quizzes, args.output_dir)
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
