"""Shared test fixtures for exporter tests."""

import pytest
from scraper.quiz_scraper import Chapter, PracticeSet, QuizQuestion


@pytest.fixture
def sample_question():
    """A single multiple-choice question with 4 choices."""
    return QuizQuestion(
        question_number=1,
        total_questions=5,
        question_type="Multiple Choice",
        question_text="What is the standard of review for a motion to dismiss?",
        choices=[
            {"label": "A", "text": "De novo review", "is_correct": True},
            {"label": "B", "text": "Abuse of discretion", "is_correct": False},
            {"label": "C", "text": "Clearly erroneous", "is_correct": False},
            {"label": "D", "text": "Substantial evidence", "is_correct": False},
        ],
        correct_answer="A",
        explanation="A motion to dismiss is reviewed de novo because it is a legal question.",
        source_url="https://coreknowledgeforlawyers.com/quiz/1",
    )


@pytest.fixture
def sample_question_no_explanation():
    """A question without an explanation."""
    return QuizQuestion(
        question_number=2,
        total_questions=5,
        question_type="Multiple Choice",
        question_text="Which court has original jurisdiction?",
        choices=[
            {"label": "A", "text": "District court", "is_correct": False},
            {"label": "B", "text": "Supreme Court", "is_correct": True},
            {"label": "C", "text": "Court of Appeals", "is_correct": False},
        ],
        correct_answer="B",
        explanation="",
        source_url="https://coreknowledgeforlawyers.com/quiz/2",
    )


@pytest.fixture
def sample_chapter(sample_question, sample_question_no_explanation):
    """A chapter with two questions."""
    return Chapter(
        chapter_name="Chapter 1: Introduction to Civil Procedure",
        launch_url="https://coreknowledgeforlawyers.com/chapter/1",
        status="Complete",
        questions=[sample_question, sample_question_no_explanation],
    )


@pytest.fixture
def sample_practice_sets(sample_chapter):
    """A list with one practice set containing one chapter."""
    return [
        PracticeSet(
            title="Civil Procedure",
            url="https://coreknowledgeforlawyers.com/ps/1",
            chapters=[sample_chapter],
        )
    ]


@pytest.fixture
def empty_practice_sets():
    """Empty practice sets list."""
    return []


@pytest.fixture
def special_chars_question():
    """A question with special characters that need escaping."""
    return QuizQuestion(
        question_number=1,
        total_questions=1,
        question_type="Multiple Choice",
        question_text='What does "res judicata" mean? Consider: {claim preclusion} & ~issue preclusion.',
        choices=[
            {"label": "A", "text": "Claim preclusion: prevents re-litigation", "is_correct": True},
            {"label": "B", "text": "Issue preclusion = collateral estoppel", "is_correct": False},
        ],
        correct_answer="A",
        explanation='The term "res judicata" literally means "a matter judged." It prevents re-litigation of claims.',
        source_url="https://coreknowledgeforlawyers.com/quiz/special",
    )


@pytest.fixture
def special_chars_practice_sets(special_chars_question):
    """Practice sets with special characters for escaping tests."""
    ch = Chapter(
        chapter_name="Ch 3: Preclusion & Res Judicata",
        launch_url="https://coreknowledgeforlawyers.com/chapter/special",
        status="Complete",
        questions=[special_chars_question],
    )
    return [
        PracticeSet(
            title="Civil Procedure: Cases & Materials",
            url="https://coreknowledgeforlawyers.com/ps/special",
            chapters=[ch],
        )
    ]
