"""Tests for the site plugin system."""

from scraper.base import BaseScraper
from scraper.sites import DEFAULT_SITE, SITE_SCRAPERS
from scraper.sites.ckl import CKLScraper


class TestSiteRegistry:
    def test_default_site_is_ckl(self):
        assert DEFAULT_SITE == "ckl"

    def test_ckl_is_registered(self):
        assert "ckl" in SITE_SCRAPERS

    def test_ckl_scraper_is_base_scraper_subclass(self):
        assert issubclass(CKLScraper, BaseScraper)

    def test_all_registered_scrapers_are_subclasses(self):
        for name, cls in SITE_SCRAPERS.items():
            assert issubclass(cls, BaseScraper), f"{name} must subclass BaseScraper"

    def test_ckl_scraper_has_site_name(self):
        assert CKLScraper.SITE_NAME == "Core Knowledge for Lawyers"

    def test_ckl_scraper_has_base_url(self):
        assert "coreknowledgeforlawyers" in CKLScraper.BASE_URL


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
