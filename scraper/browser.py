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

    Attempts multiple common login page patterns to find the login form.
    Returns True if login appears successful, False otherwise.
    """
    if not config.USERNAME or not config.PASSWORD:
        raise ValueError(
            "CKL_USERNAME and CKL_PASSWORD must be set in .env file"
        )

    base = config.BASE_URL.rstrip("/")
    login_paths = [
        "/login",
        "/log-in",
        "/signin",
        "/sign-in",
        "/wp-login.php",
        "/my-account",
        "/account/login",
    ]

    driver.get(base)
    time.sleep(2)

    # Check if there's a login link on the homepage
    login_url = _find_login_link(driver, base)
    if login_url:
        driver.get(login_url)
        time.sleep(2)
    else:
        # Try common login paths
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
    """Find and fill the login form, then submit it."""
    wait = WebDriverWait(driver, 10)

    try:
        # Find the password field first (most reliable indicator of login form)
        password_field = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "input[type='password']")
            )
        )

        # Find the username/email field - look for text/email input before the password field
        username_field = None
        selectors = [
            "input[type='email']",
            "input[name='username']",
            "input[name='email']",
            "input[name='log']",
            "input[name='user_login']",
            "input[name='login_email']",
            "input[type='text']",
        ]
        for selector in selectors:
            fields = driver.find_elements(By.CSS_SELECTOR, selector)
            for field in fields:
                if field.is_displayed():
                    username_field = field
                    break
            if username_field:
                break

        if not username_field:
            logger.error("Could not find username/email input field")
            return False

        # Fill in credentials
        username_field.clear()
        username_field.send_keys(config.USERNAME)
        password_field.clear()
        password_field.send_keys(config.PASSWORD)

        # Find and click submit button
        submit_btn = None
        btn_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button.login-btn",
            "button.signin-btn",
            "#login-btn",
        ]
        for selector in btn_selectors:
            btns = driver.find_elements(By.CSS_SELECTOR, selector)
            for btn in btns:
                if btn.is_displayed():
                    submit_btn = btn
                    break
            if submit_btn:
                break

        if not submit_btn:
            # Fallback: submit the form directly
            form = password_field.find_element(By.XPATH, "./ancestor::form")
            form.submit()
        else:
            submit_btn.click()

        time.sleep(3)

        # Verify login success - check we're no longer on a login page
        current_url = driver.current_url.lower()
        if "login" in current_url or "signin" in current_url:
            # Check for error messages
            error_selectors = [".error", ".alert-danger", ".login-error", "#login-error"]
            for selector in error_selectors:
                errors = driver.find_elements(By.CSS_SELECTOR, selector)
                for err in errors:
                    if err.is_displayed() and err.text.strip():
                        logger.error("Login failed: %s", err.text.strip())
                        return False

        logger.info("Login successful. Current URL: %s", driver.current_url)
        return True

    except Exception as e:
        logger.error("Login failed with error: %s", e)
        return False
