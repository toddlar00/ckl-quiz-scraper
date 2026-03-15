"""Browser setup, login management, and diagnostic utilities."""

import json
import logging
import os
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from scraper import config

logger = logging.getLogger(__name__)

COOKIES_FILE = ".ckl_cookies.json"
SCREENSHOT_DIR = "debug_screenshots"


def create_driver():
    """Create and configure a Chrome WebDriver instance."""
    options = Options()
    if config.HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # Reduce detection of automated browsing
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        logger.error(
            "Failed to create Chrome WebDriver. Ensure Chrome is installed.\n"
            "  Error: %s\n"
            "  Troubleshooting:\n"
            "    - Install Chrome: sudo apt install google-chrome-stable\n"
            "    - Or use Chromium: sudo apt install chromium-browser\n"
            "    - Ensure matching chromedriver is available",
            e,
        )
        raise

    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    driver.implicitly_wait(config.IMPLICIT_WAIT)
    return driver


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def save_screenshot(driver, name="error"):
    """Save a screenshot for debugging. Returns the file path or None."""
    try:
        Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(SCREENSHOT_DIR, f"{name}_{ts}.png")
        driver.save_screenshot(filepath)
        logger.info("Screenshot saved: %s", filepath)
        return filepath
    except Exception as e:
        logger.debug("Could not save screenshot: %s", e)
        return None


def dump_page_source(driver, name="error"):
    """Save the current page HTML source for debugging."""
    try:
        Path(SCREENSHOT_DIR).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(SCREENSHOT_DIR, f"{name}_{ts}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info("Page source saved: %s", filepath)
        return filepath
    except Exception as e:
        logger.debug("Could not save page source: %s", e)
        return None


def diagnose_page(driver, context="unknown"):
    """Capture screenshot + page source for debugging a failure."""
    logger.info("Capturing diagnostics for: %s (URL: %s)", context, driver.current_url)
    save_screenshot(driver, context)
    dump_page_source(driver, context)


# ---------------------------------------------------------------------------
# Cookie persistence (skip re-login between runs)
# ---------------------------------------------------------------------------

def save_cookies(driver):
    """Save browser cookies to disk for session reuse."""
    try:
        cookies = driver.get_cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
        logger.debug("Saved %d cookies to %s", len(cookies), COOKIES_FILE)
    except Exception as e:
        logger.debug("Could not save cookies: %s", e)


def load_cookies(driver):
    """Load cookies from disk and add them to the browser session.

    Returns True if cookies were loaded successfully.
    """
    if not os.path.exists(COOKIES_FILE):
        return False
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        # Must navigate to the domain first before adding cookies
        base = config.BASE_URL.rstrip("/")
        driver.get(base)
        time.sleep(2)
        for cookie in cookies:
            # Remove problematic fields that may differ across sessions
            cookie.pop("sameSite", None)
            cookie.pop("expiry", None)
            try:
                driver.add_cookie(cookie)
            except Exception:
                continue
        logger.debug("Loaded %d cookies from %s", len(cookies), COOKIES_FILE)
        return True
    except Exception as e:
        logger.debug("Could not load cookies: %s", e)
        return False


def is_logged_in(driver):
    """Check whether we appear to be logged in (post-login page content)."""
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        # After login, homepage greets "Hello, <Name>" and shows practice sets
        if "hello," in page_text or "practice set" in page_text.lower():
            return True
        # Still on login page
        if "registered users log in here" in page_text:
            return False
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(driver):
    """Log into CKL. Tries saved cookies first, then email/password form.

    Returns True on success, False on failure.
    """
    if not config.USERNAME or not config.PASSWORD:
        raise ValueError(
            "CKL_USERNAME and CKL_PASSWORD must be set in .env file. "
            "Copy .env.example to .env and fill in your credentials."
        )

    base = config.BASE_URL.rstrip("/")

    # Try cookies first for fast re-login
    if os.path.exists(COOKIES_FILE):
        logger.info("Attempting login via saved cookies...")
        if load_cookies(driver):
            driver.get(base)
            time.sleep(3)
            if is_logged_in(driver):
                logger.info("Cookie login successful!")
                return True
            logger.info("Cookie login failed, falling back to form login")

    # Navigate to homepage (login form is there)
    driver.get(base)
    time.sleep(3)

    if not _has_login_form(driver):
        # Fallback: try common login paths
        for path in ["/login", "/log-in", "/signin", "/wp-login.php"]:
            try:
                driver.get(base + path)
                time.sleep(2)
                if _has_login_form(driver):
                    break
            except Exception:
                continue

    if not _has_login_form(driver):
        logger.error("Could not find a login form on the page.")
        diagnose_page(driver, "login_no_form")
        return False

    success = _submit_login(driver)

    if success:
        save_cookies(driver)
    else:
        diagnose_page(driver, "login_failed")

    return success


def _has_login_form(driver):
    """Check if the current page contains a login form."""
    try:
        password_fields = driver.find_elements(
            By.CSS_SELECTOR, "input[type='password']"
        )
        return any(f.is_displayed() for f in password_fields)
    except Exception:
        return False


def _submit_login(driver):
    """Fill and submit the CKL login form."""
    wait = WebDriverWait(driver, 15)

    try:
        password_field = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "input[type='password']")
            )
        )

        # Find the email field
        email_field = None
        for selector in [
            "input[type='email']",
            "input[name='email']", "input[name='Email']",
            "input[name='username']", "input[name='log']",
            "input[type='text']",
        ]:
            fields = driver.find_elements(By.CSS_SELECTOR, selector)
            for field in fields:
                if field.is_displayed():
                    email_field = field
                    break
            if email_field:
                break

        if not email_field:
            logger.error("Could not find email input field")
            diagnose_page(driver, "login_no_email_field")
            return False

        # Fill in credentials
        email_field.clear()
        email_field.send_keys(config.USERNAME)
        time.sleep(0.3)
        password_field.clear()
        password_field.send_keys(config.PASSWORD)
        time.sleep(0.3)

        # Find and click the "Log In" button
        submit_btn = _find_login_button(driver)

        if submit_btn:
            submit_btn.click()
        else:
            # Fallback: submit the form directly
            form = password_field.find_element(By.XPATH, "./ancestor::form")
            form.submit()

        # Wait for page to change
        time.sleep(4)

        # Verify login success
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        error_indicators = [
            "invalid email", "invalid password", "incorrect password",
            "login failed", "authentication failed", "wrong password",
            "error", "unable to log in",
        ]
        for indicator in error_indicators:
            if indicator in page_text:
                logger.error("Login failed: '%s' found on page", indicator)
                return False

        if "registered users log in here" in page_text:
            logger.error(
                "Login form still visible after submit. "
                "Credentials may be incorrect, or the site structure changed."
            )
            return False

        logger.info("Login successful. URL: %s", driver.current_url)
        return True

    except Exception as e:
        logger.error("Login failed: %s", e)
        return False


def _find_login_button(driver):
    """Find the Log In / Submit button."""
    for selector in ["input[type='submit']", "button[type='submit']"]:
        btns = driver.find_elements(By.CSS_SELECTOR, selector)
        for btn in btns:
            if btn.is_displayed():
                return btn

    # Search by button text — CKL uses "Log In"
    try:
        for btn in driver.find_elements(
            By.CSS_SELECTOR, "button, input[type='button'], a.btn"
        ):
            btn_text = (btn.text or btn.get_attribute("value") or "").strip().lower()
            if btn_text in ("log in", "login", "sign in", "submit"):
                if btn.is_displayed():
                    return btn
    except Exception:
        pass

    return None
