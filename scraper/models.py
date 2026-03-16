"""Data models for quiz scraping.

Contains the core dataclasses used across the scraper: QuizQuestion, Chapter,
and PracticeSet. Also provides validation utilities for extracted data.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QuizQuestion:
    """A single quiz question with choices, correct answer, and explanation.

    Each choice dict has keys: label, text, is_correct, explanation.
    The top-level `explanation` is the general/correct-answer explanation.
    Per-choice explanations explain why each specific choice is correct or incorrect.
    """
    question_number: int
    total_questions: int
    question_type: str  # e.g. "Multiple Choice"
    question_text: str
    choices: list[dict] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    choice_explanations: dict = field(default_factory=dict)  # {"A": "...", "B": "..."}
    source_url: str = ""

    def validate(self):
        """Validate the question data and return a list of warnings.

        Returns:
            List of warning strings. Empty list if the question is valid.
        """
        warnings = []

        if not self.question_text or not self.question_text.strip():
            warnings.append(
                f"Q{self.question_number}: Empty question text"
            )

        if self.question_type in ("Multiple Choice", "True/False", "Select All That Apply"):
            if len(self.choices) < 2:
                warnings.append(
                    f"Q{self.question_number}: Only {len(self.choices)} choice(s) "
                    f"(expected at least 2 for {self.question_type})"
                )

        if self.correct_answer and self.choices:
            choice_labels = {c.get("label") for c in self.choices}
            if self.correct_answer not in choice_labels:
                warnings.append(
                    f"Q{self.question_number}: Correct answer '{self.correct_answer}' "
                    f"not found in choices {choice_labels}"
                )

        if not self.correct_answer:
            warnings.append(
                f"Q{self.question_number}: No correct answer identified"
            )

        return warnings


@dataclass
class Chapter:
    """A chapter within a practice set containing quiz questions."""
    chapter_name: str
    launch_url: str
    status: str = ""  # "In Progress", "To Do", etc.
    questions: list[QuizQuestion] = field(default_factory=list)


@dataclass
class PracticeSet:
    """A practice set (book) containing chapters with questions."""
    title: str
    url: str
    chapters: list[Chapter] = field(default_factory=list)


def validate_practice_sets(practice_sets):
    """Validate all questions in practice sets and log warnings.

    Args:
        practice_sets: List of PracticeSet objects.

    Returns:
        Total number of warnings found.
    """
    total_warnings = 0
    for ps in practice_sets:
        for ch in ps.chapters:
            for q in ch.questions:
                warnings = q.validate()
                for w in warnings:
                    logger.warning("  Validation: [%s / %s] %s", ps.title, ch.chapter_name, w)
                    total_warnings += 1
    return total_warnings
