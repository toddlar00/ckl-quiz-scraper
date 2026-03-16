"""Shared test fixtures for exporter tests."""

import pytest
from scraper.models import Chapter, PracticeSet, QuizQuestion


@pytest.fixture
def sample_question():
    """A single multiple-choice question with 4 choices and per-choice explanations."""
    return QuizQuestion(
        question_number=1,
        total_questions=5,
        question_type="Multiple Choice",
        question_text="What is the standard of review for a motion to dismiss?",
        choices=[
            {"label": "A", "text": "De novo review", "is_correct": True,
             "explanation": "Correct. De novo review applies because a motion to dismiss presents a legal question."},
            {"label": "B", "text": "Abuse of discretion", "is_correct": False,
             "explanation": "Incorrect. Abuse of discretion applies to discretionary rulings, not legal questions."},
            {"label": "C", "text": "Clearly erroneous", "is_correct": False,
             "explanation": "Incorrect. Clearly erroneous applies to findings of fact, not legal conclusions."},
            {"label": "D", "text": "Substantial evidence", "is_correct": False,
             "explanation": "Incorrect. Substantial evidence is used for administrative agency review."},
        ],
        correct_answer="A",
        explanation="A motion to dismiss is reviewed de novo because it is a legal question.",
        choice_explanations={
            "A": "Correct. De novo review applies because a motion to dismiss presents a legal question.",
            "B": "Incorrect. Abuse of discretion applies to discretionary rulings, not legal questions.",
            "C": "Incorrect. Clearly erroneous applies to findings of fact, not legal conclusions.",
            "D": "Incorrect. Substantial evidence is used for administrative agency review.",
        },
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
            {"label": "A", "text": "District court", "is_correct": False, "explanation": ""},
            {"label": "B", "text": "Supreme Court", "is_correct": True, "explanation": ""},
            {"label": "C", "text": "Court of Appeals", "is_correct": False, "explanation": ""},
        ],
        correct_answer="B",
        explanation="",
        choice_explanations={},
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
            {"label": "A", "text": "Claim preclusion: prevents re-litigation", "is_correct": True,
             "explanation": "Correct. Res judicata prevents re-litigation of claims."},
            {"label": "B", "text": "Issue preclusion = collateral estoppel", "is_correct": False,
             "explanation": "Incorrect. Issue preclusion is a related but distinct concept."},
        ],
        correct_answer="A",
        explanation='The term "res judicata" literally means "a matter judged." It prevents re-litigation of claims.',
        choice_explanations={
            "A": "Correct. Res judicata prevents re-litigation of claims.",
            "B": "Incorrect. Issue preclusion is a related but distinct concept.",
        },
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
