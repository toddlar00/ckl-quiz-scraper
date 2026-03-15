"""Google OAuth login handler for Selenium.

Handles the "Sign in with Google" flow that many academic platforms use:
  1. Click the Google sign-in button on the site
  2. Handle popup window or redirect to accounts.google.com
  3. Enter Google email and password
  4. Return to the originating site after authentication
"""

import logging
import time

from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# Common selectors for "Sign in with Google" buttons across sites
GOOGLE_BUTTON_SELECTORS = [
    # Standard Google Identity Services button
    "div[id='g_id_signin']",
    "div[class*='g_id_signin']",
    # Common custom implementations
    "a[href*='accounts.google.com']",
    "a[href*='google.com/o/oauth']",
    "button[data-provider='google']",
    "a[data-provider='google']",
    # Class-based patterns
    "button.google-login",
    "a.google-login",
    "button.google-signin",
    "a.google-signin",
    "button.btn-google",
    "a.btn-google",
    ".social-login-google",
    # Image-based Google buttons
    "img[alt*='Google']",
    "img[src*='google']",
]

# Text patterns that identify a Google login button
GOOGLE_BUTTON_TEXTS = [
    "sign in with google",
    "continue with google",
    "log in with google",
    "google",
]


def find_google_login_button(driver):
    """Find a 'Sign in with Google' button on the current page.

    Returns:
        WebElement if found, None otherwise.
    """
    # Try CSS selectors first
    for selector in GOOGLE_BUTTON_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed():
                    logger.debug("Found Google button via selector: %s", selector)
                    return el
        except Exception:
            continue

    # Try finding by button/link text
    for tag in ["button", "a", "div", "span"]:
        try:
            elements = driver.find_elements(By.TAG_NAME, tag)
            for el in elements:
                try:
                    text = (el.text or el.get_attribute("value") or "").strip().lower()
                    aria = (el.get_attribute("aria-label") or "").strip().lower()
                    title = (el.get_attribute("title") or "").strip().lower()
                    combined = f"{text} {aria} {title}"
                    if any(gt in combined for gt in GOOGLE_BUTTON_TEXTS):
                        if el.is_displayed():
                            logger.debug("Found Google button via text: '%s'", text)
                            return el
                except Exception:
                    continue
        except Exception:
            continue

    # Try iframes (Google Identity Services renders inside iframe)
    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            src = (iframe.get_attribute("src") or "").lower()
            if "accounts.google.com" in src or "gsi" in src:
                driver.switch_to.frame(iframe)
                try:
                    # Inside the Google iframe, look for the sign-in container
                    container = driver.find_elements(By.CSS_SELECTOR, "div[role='button']")
                    for el in container:
                        if el.is_displayed():
                            logger.debug("Found Google button inside iframe")
                            return el
                finally:
                    driver.switch_to.default_content()
    except Exception:
        pass

    return None


def google_login(driver, email, password, timeout=30):
    """Complete the Google OAuth login flow on accounts.google.com.

    Assumes the browser has already been redirected to or has opened
    the Google sign-in page (accounts.google.com).

    Args:
        driver: Selenium WebDriver.
        email: Google account email.
        password: Google account password.
        timeout: Max wait time for elements (seconds).

    Returns:
        True on success, False on failure.
    """
    wait = WebDriverWait(driver, timeout)

    try:
        # Step 1: Enter email
        logger.debug("Google login: entering email...")
        email_field = _find_google_email_field(wait, driver)
        if not email_field:
            logger.error("Could not find Google email field")
            return False

        email_field.clear()
        email_field.send_keys(email)
        time.sleep(0.5)

        # Click Next
        _click_google_next(driver)
        time.sleep(2)

        # Step 2: Enter password
        logger.debug("Google login: entering password...")
        password_field = _find_google_password_field(wait, driver)
        if not password_field:
            logger.error("Could not find Google password field")
            return False

        password_field.clear()
        password_field.send_keys(password)
        time.sleep(0.5)

        # Click Next
        _click_google_next(driver)
        time.sleep(3)

        # Step 3: Handle consent screen if present
        _handle_google_consent(driver)

        logger.info("Google login flow completed")
        return True

    except TimeoutException:
        logger.error("Google login timed out waiting for page elements")
        return False
    except Exception as e:
        logger.error("Google login failed: %s", e)
        return False


def google_login_via_button(driver, email, password, timeout=30):
    """Click the Google login button on the current page and complete OAuth flow.

    Handles both popup and redirect-based Google OAuth flows.

    Args:
        driver: Selenium WebDriver on a page with a Google sign-in button.
        email: Google account email.
        password: Google account password.
        timeout: Max wait time for elements (seconds).

    Returns:
        True on success, False on failure.
    """
    google_btn = find_google_login_button(driver)
    if not google_btn:
        logger.error("No Google sign-in button found on page")
        return False

    original_window = driver.current_window_handle
    original_windows = set(driver.window_handles)

    logger.info("Clicking Google sign-in button...")
    try:
        google_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", google_btn)
    time.sleep(3)

    # Check if a popup window opened
    new_windows = set(driver.window_handles) - original_windows
    if new_windows:
        # Popup flow: switch to the new Google window
        popup = new_windows.pop()
        driver.switch_to.window(popup)
        logger.debug("Switched to Google popup window")

        success = google_login(driver, email, password, timeout)

        # After completing login, the popup typically closes itself.
        # Switch back to the original window.
        time.sleep(3)
        try:
            if popup in driver.window_handles:
                # Popup didn't close — consent may be needed
                driver.switch_to.window(popup)
                _handle_google_consent(driver)
                time.sleep(2)
        except Exception:
            pass

        driver.switch_to.window(original_window)
        time.sleep(3)
        return success

    else:
        # Redirect flow: the current page redirected to accounts.google.com
        current_url = driver.current_url.lower()
        if "accounts.google.com" in current_url:
            success = google_login(driver, email, password, timeout)
            time.sleep(3)
            return success
        else:
            # Check if we're on a Google-related page
            logger.warning(
                "Google button clicked but didn't navigate to Google. URL: %s",
                driver.current_url,
            )
            # Wait a moment and check again
            time.sleep(3)
            current_url = driver.current_url.lower()
            if "accounts.google.com" in current_url:
                return google_login(driver, email, password, timeout)
            return False


def _find_google_email_field(wait, driver):
    """Find the email/identifier input on the Google sign-in page."""
    selectors = [
        "input[type='email']",
        "input[name='identifier']",
        "#identifierId",
        "input[id='identifierId']",
    ]
    for selector in selectors:
        try:
            field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            if field.is_displayed():
                return field
        except TimeoutException:
            continue

    # Fallback: any visible text input
    try:
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
        for inp in inputs:
            if inp.is_displayed():
                return inp
    except Exception:
        pass

    return None


def _find_google_password_field(wait, driver):
    """Find the password input on the Google sign-in page."""
    selectors = [
        "input[type='password']",
        "input[name='Passwd']",
        "input[name='password']",
    ]
    for selector in selectors:
        try:
            field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
            )
            if field.is_displayed():
                return field
        except TimeoutException:
            continue
    return None


def _click_google_next(driver):
    """Click the 'Next' button on a Google sign-in page."""
    selectors = [
        "#identifierNext",
        "#passwordNext",
        "button[type='submit']",
    ]
    for selector in selectors:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, selector)
            for btn in btns:
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    return
        except Exception:
            continue

    # Fallback: find by text
    for el in driver.find_elements(By.CSS_SELECTOR, "button, span"):
        try:
            text = el.text.strip().lower()
            if text in ("next", "continue"):
                if el.is_displayed():
                    el.click()
                    return
        except Exception:
            continue


def _handle_google_consent(driver):
    """Handle the Google OAuth consent/permission screen if it appears."""
    try:
        time.sleep(1)
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        consent_indicators = ["wants to access", "allow", "grant access", "choose an account"]

        if any(ind in body for ind in consent_indicators):
            logger.debug("Google consent screen detected")
            # Click "Allow" or "Continue"
            for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
                text = btn.text.strip().lower()
                if text in ("allow", "continue", "accept"):
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(2)
                        return

            # Try "Choose an account" flow — click the matching email
            for el in driver.find_elements(By.CSS_SELECTOR, "div[data-email], li"):
                try:
                    if el.is_displayed():
                        el.click()
                        time.sleep(2)
                        return
                except Exception:
                    continue
    except Exception:
        pass
