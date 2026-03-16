"""Tests for data models and validation."""

import pytest
from scraper.models import QuizQuestion, Chapter, PracticeSet, validate_practice_sets


class TestQuizQuestionValidation:
    """Test QuizQuestion.validate() method."""

    def test_valid_question_no_warnings(self):
        q = QuizQuestion(
            question_number=1, total_questions=5,
            question_type="Multiple Choice",
            question_text="What is X?",
            choices=[
                {"label": "A", "text": "One", "is_correct": True},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
            correct_answer="A",
        )
        assert q.validate() == []

    def test_empty_question_text(self):
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC", question_text="",
        )
        warnings = q.validate()
        assert any("Empty question text" in w for w in warnings)

    def test_whitespace_only_question_text(self):
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC", question_text="   ",
        )
        warnings = q.validate()
        assert any("Empty question text" in w for w in warnings)

    def test_too_few_choices_for_mc(self):
        q = QuizQuestion(
            question_number=2, total_questions=5,
            question_type="Multiple Choice",
            question_text="What is X?",
            choices=[{"label": "A", "text": "Only one", "is_correct": True}],
            correct_answer="A",
        )
        warnings = q.validate()
        assert any("Only 1 choice" in w for w in warnings)

    def test_no_choices_for_mc(self):
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Multiple Choice",
            question_text="What?",
            choices=[],
            correct_answer="A",
        )
        warnings = q.validate()
        assert any("0 choice" in w for w in warnings)

    def test_correct_answer_not_in_choices(self):
        q = QuizQuestion(
            question_number=3, total_questions=5,
            question_type="Multiple Choice",
            question_text="What is X?",
            choices=[
                {"label": "A", "text": "One", "is_correct": False},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
            correct_answer="D",
        )
        warnings = q.validate()
        assert any("not found in choices" in w for w in warnings)

    def test_no_correct_answer(self):
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Multiple Choice",
            question_text="What?",
            choices=[
                {"label": "A", "text": "One", "is_correct": False},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
            correct_answer="",
        )
        warnings = q.validate()
        assert any("No correct answer" in w for w in warnings)

    def test_fill_in_blank_no_choice_validation(self):
        """Fill-in-the-blank doesn't require choices."""
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Fill in the Blank",
            question_text="The answer is ___.",
            choices=[],
            correct_answer="A",
        )
        warnings = q.validate()
        # Should NOT warn about too few choices for fill-in
        assert not any("choice" in w.lower() for w in warnings)

    def test_multiple_warnings(self):
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Multiple Choice",
            question_text="",
            choices=[],
            correct_answer="",
        )
        warnings = q.validate()
        assert len(warnings) >= 2  # Empty text + no choices + no correct answer


class TestValidatePracticeSets:
    def test_counts_warnings(self):
        q1 = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC", question_text="",
        )
        q2 = QuizQuestion(
            question_number=2, total_questions=1,
            question_type="MC", question_text="Valid question",
            correct_answer="A",
            choices=[
                {"label": "A", "text": "X", "is_correct": True},
                {"label": "B", "text": "Y", "is_correct": False},
            ],
        )
        ch = Chapter(chapter_name="Ch1", launch_url="url", questions=[q1, q2])
        ps = PracticeSet(title="PS1", url="url", chapters=[ch])
        count = validate_practice_sets([ps])
        assert count >= 1  # q1 has empty text

    def test_empty_practice_sets(self):
        assert validate_practice_sets([]) == 0
