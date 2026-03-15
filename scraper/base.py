"""Base scraper interface for quiz websites.

To add support for a new quiz site:
  1. Create a new module in scraper/sites/ (e.g., quizlet_live.py)
  2. Subclass BaseScraper and implement all abstract methods
  3. Register in scraper/sites/__init__.py
  4. The framework handles login, progress tracking, adaptive delay, and export
"""

import logging
from abc import ABC, abstractmethod

from scraper.quiz_scraper import (
    Chapter,
    PracticeSet,
    QuizQuestion,
    _get_body_text,
    _retry,
    _safe_click,
    _safe_get,
    get_adaptive_delay,
    is_chapter_completed,
    mark_chapter_completed,
)

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for quiz website scrapers.

    Subclasses implement site-specific discovery and extraction logic.
    The framework provides: driver management, adaptive delays, progress
    tracking, retry logic, and export to all formats.
    """

    # Override in subclass
    SITE_NAME = "Unknown"
    BASE_URL = ""
    REQUIRES_LOGIN = True

    def __init__(self, driver):
        self.driver = driver

    # ------------------------------------------------------------------
    # Abstract methods — must be implemented by each site scraper
    # ------------------------------------------------------------------

    @abstractmethod
    def login(self, username, password):
        """Log into the site. Return True on success, False on failure."""

    @abstractmethod
    def discover_practice_sets(self):
        """Find all available practice sets / quiz collections.

        Returns:
            List of (title, url) tuples.
        """

    @abstractmethod
    def discover_chapters(self, practice_set_url):
        """Find all chapters / sections within a practice set.

        Returns:
            List of Chapter objects.
        """

    @abstractmethod
    def extract_question(self, body_text):
        """Extract question text from cached page body text.

        Args:
            body_text: The full text content of the page.

        Returns:
            Tuple of (question_type, question_text) or (None, None) on failure.
        """

    @abstractmethod
    def extract_choices(self, body_text):
        """Extract answer choices from the page.

        Args:
            body_text: Cached page text (for text-based extraction).

        Returns:
            List of dicts with keys: label, text, is_correct.
        """

    @abstractmethod
    def submit_answer(self):
        """Select an answer and submit to reveal feedback.

        This method should interact with the page (click radio, submit).
        """

    @abstractmethod
    def extract_feedback(self, body_text):
        """Extract correct answer and explanation from post-submit feedback.

        Args:
            body_text: Cached post-submit page text.

        Returns:
            Tuple of (correct_answer, explanation).
        """

    @abstractmethod
    def click_next_question(self):
        """Navigate to the next question. Returns True if successful."""

    # ------------------------------------------------------------------
    # Optional overrides
    # ------------------------------------------------------------------

    def extract_choice_explanations(self, body_text, choices, correct_answer):
        """Extract per-choice explanations from post-submit feedback.

        Override this to parse site-specific feedback that explains why each
        answer choice is correct or incorrect.

        Args:
            body_text: Post-submit page text.
            choices: List of choice dicts (label, text, is_correct).
            correct_answer: The correct answer label (e.g. "A").

        Returns:
            Dict mapping choice labels to explanation strings.
            E.g. {"A": "Correct because...", "B": "Incorrect because..."}
        """
        return {}

    def get_total_questions(self, body_text):
        """Extract total question count from page text. Override if needed.

        Returns:
            Integer count, or None if unknown.
        """
        return None

    def navigate_to_home(self):
        """Navigate to the home/dashboard page after login. Override if needed."""
        pass

    # ------------------------------------------------------------------
    # Framework methods — shared across all scrapers
    # ------------------------------------------------------------------

    def scrape_chapter(self, chapter, resume=True):
        """Scrape all questions from a chapter. Handles retries, adaptive delay, progress.

        Args:
            chapter: Chapter object to populate.
            resume: Skip if already completed in a previous run.

        Returns:
            List of QuizQuestion objects.
        """
        if resume and is_chapter_completed(chapter.launch_url):
            logger.info("  Skipping (already scraped in previous run)")
            return chapter.questions

        _safe_get(self.driver, chapter.launch_url, f"chapter: {chapter.chapter_name}")

        initial_body = _get_body_text(self.driver)
        total = self.get_total_questions(initial_body)
        logger.info("  %s question(s) to scrape", total or "Unknown number of")

        questions = []
        question_num = 0
        max_questions = total or 200
        consecutive_failures = 0

        while question_num < max_questions:
            question_num += 1
            adaptive = get_adaptive_delay()

            try:
                q = self._scrape_single_question(question_num, total or 0)
                if q:
                    questions.append(q)
                    consecutive_failures = 0
                    adaptive.on_success()
                    logger.info(
                        "  [%d/%s] %s → Answer: %s (delay: %.1fs)",
                        q.question_number,
                        total or "?",
                        q.question_text[:60] + ("..." if len(q.question_text) > 60 else ""),
                        q.correct_answer or "unknown",
                        adaptive.budget,
                    )
                else:
                    consecutive_failures += 1
                    adaptive.on_failure()
                    logger.warning("  Could not parse question %d", question_num)
                    from scraper.browser import diagnose_page
                    diagnose_page(self.driver, f"parse_fail_q{question_num}")

                if consecutive_failures >= 3:
                    logger.error(
                        "  3 consecutive failures — stopping chapter scrape.\n"
                        "  This may indicate the page structure changed."
                    )
                    from scraper.browser import diagnose_page
                    diagnose_page(self.driver, "consecutive_failures")
                    break

                if not self.click_next_question():
                    logger.info("  Finished chapter (%d questions scraped)", len(questions))
                    break

                adaptive.sleep("rate_limit")

            except Exception as e:
                consecutive_failures += 1
                adaptive.on_failure()
                logger.warning("  Error on question %d: %s", question_num, e)
                if not self.click_next_question():
                    break

        chapter.questions = questions
        mark_chapter_completed(chapter.launch_url, len(questions))
        return questions

    def _scrape_single_question(self, question_num, total):
        """Scrape one question using the site-specific extraction methods."""
        source_url = self.driver.current_url

        # Read body text once for pre-submit extraction
        pre_body = _get_body_text(self.driver)

        question_type, question_text = self.extract_question(pre_body)
        if not question_text:
            return None

        choices = self.extract_choices(pre_body)

        self.submit_answer()
        get_adaptive_delay().sleep("feedback_wait")

        # Read body text once for post-submit feedback
        post_body = _get_body_text(self.driver)
        correct_answer, explanation = self.extract_feedback(post_body)

        # Extract per-choice explanations (why each answer is correct/incorrect)
        choice_explanations = self.extract_choice_explanations(post_body, choices, correct_answer)

        # Mark correct choice and attach per-choice explanations
        for choice in choices:
            if correct_answer and choice["label"] == correct_answer:
                choice["is_correct"] = True
            choice["explanation"] = choice_explanations.get(choice["label"], "")

        return QuizQuestion(
            question_number=question_num,
            total_questions=total,
            question_type=question_type or "",
            question_text=question_text,
            choices=choices,
            correct_answer=correct_answer,
            explanation=explanation,
            choice_explanations=choice_explanations,
            source_url=source_url,
        )
