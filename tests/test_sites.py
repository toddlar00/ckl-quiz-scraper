"""Tests for the site plugin system."""

from scraper.base import BaseScraper
from scraper.sites import DEFAULT_SITE, SITE_SCRAPERS
from scraper.sites.ckl import CKLScraper
from scraper.sites.westacademic import WestAcademicScraper


class TestSiteRegistry:
    def test_default_site_is_ckl(self):
        assert DEFAULT_SITE == "ckl"

    def test_ckl_is_registered(self):
        assert "ckl" in SITE_SCRAPERS

    def test_westacademic_is_registered(self):
        assert "westacademic" in SITE_SCRAPERS

    def test_ckl_scraper_is_base_scraper_subclass(self):
        assert issubclass(CKLScraper, BaseScraper)

    def test_westacademic_scraper_is_base_scraper_subclass(self):
        assert issubclass(WestAcademicScraper, BaseScraper)

    def test_all_registered_scrapers_are_subclasses(self):
        for name, cls in SITE_SCRAPERS.items():
            assert issubclass(cls, BaseScraper), f"{name} must subclass BaseScraper"

    def test_ckl_scraper_has_site_name(self):
        assert CKLScraper.SITE_NAME == "Core Knowledge for Lawyers"

    def test_westacademic_scraper_has_site_name(self):
        assert WestAcademicScraper.SITE_NAME == "West Academic"

    def test_ckl_scraper_has_base_url(self):
        assert "coreknowledgeforlawyers" in CKLScraper.BASE_URL

    def test_westacademic_scraper_has_base_url(self):
        assert "westacademic" in WestAcademicScraper.BASE_URL

    def test_westacademic_requires_login(self):
        assert WestAcademicScraper.REQUIRES_LOGIN is True


class TestCKLExtraction:
    """Test CKL-specific text extraction methods (no driver needed)."""

    def test_detect_type_multiple_choice(self):
        assert CKLScraper._detect_type("Some text Multiple Choice here") == "Multiple Choice"

    def test_detect_type_true_false(self):
        assert CKLScraper._detect_type("True/False question") == "True/False"

    def test_detect_type_fill_in(self):
        assert CKLScraper._detect_type("Fill in the blank") == "Fill in the Blank"

    def test_detect_type_unknown(self):
        assert CKLScraper._detect_type("Just some text") == ""

    def test_extract_text_basic(self):
        body = "Multiple Choice\nWhat is res judicata?\nA. Something\nB. Other"
        result = CKLScraper._extract_text(body)
        assert "res judicata" in result

    def test_extract_text_with_marker(self):
        body = "Header stuff\n>>>> Question <<<<\nWhat is due process?\nA. First"
        result = CKLScraper._extract_text(body)
        assert "due process" in result

    def test_extract_choices_from_text(self):
        body = "Question?\nA. First choice\nB. Second choice\nC. Third\nSubmit"
        choices = CKLScraper._extract_choices_from_text(body)
        assert len(choices) == 3
        assert choices[0]["label"] == "A"
        assert choices[0]["text"] == "First choice"


class TestWestAcademicExtraction:
    """Test West Academic text extraction methods (no driver needed)."""

    def test_detect_type_multiple_choice(self):
        assert WestAcademicScraper._detect_type("Multiple Choice question") == "Multiple Choice"

    def test_detect_type_true_false(self):
        assert WestAcademicScraper._detect_type("True/False question") == "True/False"

    def test_detect_type_fill_in(self):
        assert WestAcademicScraper._detect_type("Fill in the blank") == "Fill in the Blank"

    def test_detect_type_short_answer(self):
        assert WestAcademicScraper._detect_type("Short Answer question") == "Short Answer"

    def test_detect_type_essay(self):
        assert WestAcademicScraper._detect_type("Essay format") == "Essay"

    def test_detect_type_default_mc(self):
        # West Academic defaults to Multiple Choice (Exam Pro standard)
        assert WestAcademicScraper._detect_type("Just some text") == "Multiple Choice"

    def test_extract_text_basic(self):
        body = "Multiple Choice\nWhat is personal jurisdiction?\nA. Something\nB. Other"
        result = WestAcademicScraper._extract_text(body)
        assert "personal jurisdiction" in result

    def test_extract_text_strips_type_label(self):
        body = "Multiple Choice\nWhat is standing?\nA. First"
        result = WestAcademicScraper._extract_text(body)
        assert "Multiple Choice" not in result
        assert "standing" in result

    def test_extract_choices_from_text(self):
        body = "Question?\nA. First choice\nB. Second choice\nC. Third\nSubmit"
        choices = WestAcademicScraper._extract_choices_from_text(body)
        assert len(choices) == 3
        assert choices[0]["label"] == "A"
        assert choices[0]["text"] == "First choice"

    def test_extract_choices_lowercase_labels(self):
        body = "Question?\na) First\nb) Second\nc) Third\nCheck"
        choices = WestAcademicScraper._extract_choices_from_text(body)
        assert len(choices) == 3
        assert choices[0]["label"] == "A"  # Uppercased

    def test_extract_choices_all_not_correct(self):
        body = "Q?\nA. One\nB. Two\nSubmit"
        choices = WestAcademicScraper._extract_choices_from_text(body)
        assert all(not c["is_correct"] for c in choices)


class TestCKLChoiceExplanations:
    """Test CKL per-choice explanation extraction (static, no driver needed)."""

    def test_fallback_generates_explanations(self):
        """When no per-choice feedback is found, fallback applies general explanation."""
        body = "The correct answer is B\nHere's Why: Res judicata bars re-litigation.\nNext Question"
        choices = [
            {"label": "A", "text": "Wrong answer", "is_correct": False},
            {"label": "B", "text": "Right answer", "is_correct": True},
        ]
        # Create a scraper instance without a real driver for static method test
        # The fallback path doesn't need driver
        import unittest.mock as mock
        scraper = CKLScraper.__new__(CKLScraper)
        scraper.driver = mock.MagicMock()
        scraper.driver.find_elements.return_value = []
        result = scraper.extract_choice_explanations(body, choices, "B")
        assert "B" in result
        assert "Correct" in result["B"]
        assert "Res judicata" in result["B"]
        assert "A" in result
        assert "Incorrect" in result["A"]

    def test_empty_when_no_correct_answer(self):
        """Returns empty dict when correct answer is unknown."""
        body = "Some feedback text"
        choices = [{"label": "A", "text": "Choice", "is_correct": False}]
        import unittest.mock as mock
        scraper = CKLScraper.__new__(CKLScraper)
        scraper.driver = mock.MagicMock()
        scraper.driver.find_elements.return_value = []
        result = scraper.extract_choice_explanations(body, choices, "")
        assert result == {}


class TestQuizQuestionModel:
    """Test QuizQuestion dataclass fields."""

    def test_choice_explanations_default(self):
        from scraper.quiz_scraper import QuizQuestion
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC", question_text="Test?",
        )
        assert q.choice_explanations == {}
        assert q.choices == []

    def test_choice_explanations_populated(self):
        from scraper.quiz_scraper import QuizQuestion
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC", question_text="Test?",
            choices=[
                {"label": "A", "text": "X", "is_correct": True, "explanation": "Right"},
                {"label": "B", "text": "Y", "is_correct": False, "explanation": "Wrong"},
            ],
            correct_answer="A",
            explanation="General reason",
            choice_explanations={"A": "Right", "B": "Wrong"},
        )
        assert q.choice_explanations["A"] == "Right"
        assert q.choices[1]["explanation"] == "Wrong"


class TestGoogleAuth:
    """Test Google auth helper functions (no driver needed)."""

    def test_google_button_selectors_not_empty(self):
        from scraper.google_auth import GOOGLE_BUTTON_SELECTORS
        assert len(GOOGLE_BUTTON_SELECTORS) > 0

    def test_google_button_texts_not_empty(self):
        from scraper.google_auth import GOOGLE_BUTTON_TEXTS
        assert len(GOOGLE_BUTTON_TEXTS) > 0

    def test_google_button_texts_are_lowercase(self):
        from scraper.google_auth import GOOGLE_BUTTON_TEXTS
        for text in GOOGLE_BUTTON_TEXTS:
            assert text == text.lower()
