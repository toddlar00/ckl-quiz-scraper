"""Browser setup and login management."""

import logging
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from scraper import config

logger = logging.getLogger(__name__)


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

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    driver.implicitly_wait(config.IMPLICIT_WAIT)
    return driver


def login(driver):
    """Log into the CKL website using configured credentials.

    The CKL site has the login form directly on the homepage with
    Email and Password fields and a "Log In" button.
    Returns True if login appears successful, False otherwise.
    """
    if not config.USERNAME or not config.PASSWORD:
        raise ValueError(
            "CKL_USERNAME and CKL_PASSWORD must be set in .env file"
        )

    base = config.BASE_URL.rstrip("/")

    # CKL login form is on the homepage
    driver.get(base)
    time.sleep(3)

    if not _has_login_form(driver):
        # Fallback: try common login paths
        login_paths = ["/login", "/log-in", "/signin", "/wp-login.php"]
        for path in login_paths:
            try:
                driver.get(base + path)
                time.sleep(2)
                if _has_login_form(driver):
                    break
            except Exception:
                continue

    if not _has_login_form(driver):
        logger.warning(
            "Could not find a login form. Current URL: %s", driver.current_url
        )
        return False

    return _submit_login(driver)


def _find_login_link(driver, base_url):
    """Search the current page for a link to a login page."""
    login_keywords = ["login", "log in", "sign in", "signin", "my account"]
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href") or ""
            text = link.text.lower().strip()
            if any(kw in text or kw in href.lower() for kw in login_keywords):
                return href
    except Exception:
        pass
    return None


def _has_login_form(driver):
    """Check if the current page contains a login form."""
    try:
        forms = driver.find_elements(By.TAG_NAME, "form")
        for form in forms:
            password_fields = form.find_elements(
                By.CSS_SELECTOR, "input[type='password']"
            )
            if password_fields:
                return True
    except Exception:
        pass
    return False


def _submit_login(driver):
    """Find and fill the CKL login form, then submit it.

    CKL homepage has: Email input, Password input, and a "Log In" button.
    """
    wait = WebDriverWait(driver, 10)

    try:
        # Find the password field first (most reliable indicator of login form)
        password_field = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type='password']")
            )
        )

        # Find the email field — CKL uses an email input on the homepage
        email_field = None
        selectors = [
            "input[type='email']",
            "input[name='email']",
            "input[name='Email']",
            "input[name='username']",
            "input[name='log']",
            "input[type='text']",
        ]
        for selector in selectors:
            fields = driver.find_elements(By.CSS_SELECTOR, selector)
            for field in fields:
                if field.is_displayed():
                    email_field = field
                    break
            if email_field:
                break

        if not email_field:
            logger.error("Could not find email input field")
            return False

        # Fill in credentials
        email_field.clear()
        email_field.send_keys(config.USERNAME)
        password_field.clear()
        password_field.send_keys(config.PASSWORD)

        # Find and click the "Log In" button
        submit_btn = _find_login_button(driver)

        if not submit_btn:
            # Fallback: submit the form directly
            form = password_field.find_element(By.XPATH, "./ancestor::form")
            form.submit()
        else:
            submit_btn.click()

        time.sleep(4)

        # Verify login success — check page changed or has post-login content
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        current_url = driver.current_url

        # Check for error messages on page
        error_indicators = [
            "invalid email", "invalid password", "incorrect password",
            "login failed", "authentication failed", "wrong password",
        ]
        for indicator in error_indicators:
            if indicator in page_text:
                logger.error("Login failed: found '%s' on page", indicator)
                return False

        # If we can still see "Registered Users Log In Here", login may have failed
        if "registered users log in here" in page_text:
            logger.warning("Login form still visible — login may have failed")
            return False

        logger.info("Login successful. Current URL: %s", current_url)
        return True

    except Exception as e:
        logger.error("Login failed with error: %s", e)
        return False


def _find_login_button(driver):
    """Find the Log In / Submit button."""
    # Try standard submit buttons first
    btn_selectors = [
        "input[type='submit']",
        "button[type='submit']",
    ]
    for selector in btn_selectors:
        btns = driver.find_elements(By.CSS_SELECTOR, selector)
        for btn in btns:
            if btn.is_displayed():
                return btn

    # Search by button text — CKL uses "Log In"
    login_texts = ["log in", "login", "sign in", "submit"]
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button, input[type='button'], a.btn")
        for btn in buttons:
            btn_text = (btn.text or btn.get_attribute("value") or "").strip().lower()
            if btn_text in login_texts and btn.is_displayed():
                return btn
    except Exception:
        pass

    return None
