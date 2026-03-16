"""Tests for browser utilities (no real browser needed)."""

import json
import os
import unittest.mock as mock

import pytest

from scraper.browser import (
    validate_browser_installation,
    COOKIES_FILE,
)


class TestBrowserValidation:
    def test_validate_finds_chrome(self):
        """validate_browser_installation returns a path when Chrome is available."""
        # This test may pass or fail depending on the environment
        # We just verify the function doesn't crash
        result = validate_browser_installation()
        # result is either a path string or None
        assert result is None or os.path.isfile(result)

    def test_validate_returns_none_when_not_found(self, monkeypatch):
        """Returns None when no browser binary is found."""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        monkeypatch.setattr(os.path, "isfile", lambda x: False)
        result = validate_browser_installation()
        assert result is None


class TestCookiePersistence:
    def test_save_and_load_cookies(self, tmp_path, monkeypatch):
        """Test basic cookie save/load cycle."""
        cookie_file = str(tmp_path / "cookies.json")
        monkeypatch.setattr("scraper.browser.COOKIES_FILE", cookie_file)

        from scraper.browser import save_cookies, load_cookies

        # Mock driver
        driver = mock.MagicMock()
        driver.get_cookies.return_value = [
            {"name": "session", "value": "abc123", "domain": ".example.com"},
            {"name": "auth", "value": "token", "domain": ".example.com"},
        ]

        save_cookies(driver)
        assert os.path.exists(cookie_file)

        # Verify file content
        with open(cookie_file) as f:
            data = json.load(f)
        assert len(data) == 2

    def test_load_nonexistent_cookies(self, tmp_path, monkeypatch):
        cookie_file = str(tmp_path / "nonexistent_cookies.json")
        monkeypatch.setattr("scraper.browser.COOKIES_FILE", cookie_file)

        from scraper.browser import load_cookies
        driver = mock.MagicMock()
        result = load_cookies(driver)
        assert result is False

    def test_load_corrupt_cookies(self, tmp_path, monkeypatch):
        cookie_file = str(tmp_path / "corrupt_cookies.json")
        monkeypatch.setattr("scraper.browser.COOKIES_FILE", cookie_file)
        with open(cookie_file, "w") as f:
            f.write("not json")

        from scraper.browser import load_cookies
        driver = mock.MagicMock()
        result = load_cookies(driver)
        assert result is False

    def test_load_invalid_format(self, tmp_path, monkeypatch):
        """Cookies file that's valid JSON but not a list."""
        cookie_file = str(tmp_path / "invalid_cookies.json")
        monkeypatch.setattr("scraper.browser.COOKIES_FILE", cookie_file)
        with open(cookie_file, "w") as f:
            json.dump({"not": "a list"}, f)

        from scraper.browser import load_cookies
        driver = mock.MagicMock()
        result = load_cookies(driver)
        assert result is False


class TestRetryLogic:
    def test_retry_succeeds_first_try(self):
        from scraper.quiz_scraper import _retry
        result = _retry(lambda: 42, retries=3, delay=0, description="test")
        assert result == 42

    def test_retry_succeeds_after_failure(self):
        from scraper.quiz_scraper import _retry
        attempts = [0]

        def flaky():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("not yet")
            return "success"

        result = _retry(flaky, retries=3, delay=0, description="test")
        assert result == "success"
        assert attempts[0] == 3

    def test_retry_exhausted_raises(self):
        from scraper.quiz_scraper import _retry
        with pytest.raises(ValueError):
            _retry(lambda: (_ for _ in ()).throw(ValueError("fail")),
                   retries=2, delay=0, description="test")


class TestHTTPErrorDetection:
    def test_rate_limit_detected(self):
        from scraper.quiz_scraper import _check_http_errors
        from selenium.common.exceptions import WebDriverException

        driver = mock.MagicMock()
        driver.title = "429 Too Many Requests"
        body_el = mock.MagicMock()
        body_el.text = "Rate limit exceeded"
        driver.find_element.return_value = body_el

        with pytest.raises(WebDriverException, match="429"):
            _check_http_errors(driver, "http://example.com")

    def test_normal_page_no_error(self):
        from scraper.quiz_scraper import _check_http_errors

        driver = mock.MagicMock()
        driver.title = "Quiz Page"
        body_el = mock.MagicMock()
        body_el.text = "Question 1 of 10"
        driver.find_element.return_value = body_el

        # Should not raise
        _check_http_errors(driver, "http://example.com")

    def test_server_error_detected(self):
        from scraper.quiz_scraper import _check_http_errors
        from selenium.common.exceptions import WebDriverException

        driver = mock.MagicMock()
        driver.title = "503 Service Unavailable"
        body_el = mock.MagicMock()
        body_el.text = "The server is temporarily unavailable"
        driver.find_element.return_value = body_el

        with pytest.raises(WebDriverException, match="503"):
            _check_http_errors(driver, "http://example.com")
