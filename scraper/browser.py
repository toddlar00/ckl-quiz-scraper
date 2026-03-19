"""Browser setup, login management, and diagnostic utilities."""

import json
import logging
import os
import random
import shutil
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper import config

logger = logging.getLogger(__name__)

COOKIES_FILE = ".ckl_cookies.json"


def _add_proxy_auth_extension(options, parsed_url):
    """Create a temporary Chrome extension that handles proxy authentication.

    Chrome's --proxy-server flag doesn't support user:pass in the URL.
    This injects a minimal extension that responds to proxy auth challenges.
    """
    import tempfile
    import zipfile

    manifest = """{
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Proxy Auth",
        "permissions": ["proxy", "webRequest", "webRequestBlocking", "<all_urls>"],
        "background": {"scripts": ["background.js"]}
    }"""

    background = """
    chrome.webRequest.onAuthRequired.addListener(
        function(details) {
            return {
                authCredentials: {
                    username: "%s",
                    password: "%s"
                }
            };
        },
        {urls: ["<all_urls>"]},
        ["blocking"]
    );
    """ % (parsed_url.username.replace('"', '\\"'),
           parsed_url.password.replace('"', '\\"'))

    ext_path = tempfile.NamedTemporaryFile(suffix=".zip", delete=False).name
    with zipfile.ZipFile(ext_path, "w") as zf:
        zf.writestr("manifest.json", manifest)
        zf.writestr("background.js", background)

    options.add_extension(ext_path)
    logger.debug("Added proxy auth extension for user: %s", parsed_url.username)
SCREENSHOT_DIR = "debug_screenshots"


def validate_browser_installation():
    """Check that Chrome or Chromium is installed and accessible.

    Searches PATH, common install directories on Linux/macOS/Windows,
    Snap, Flatpak, Nix, Homebrew, and user-local locations. Logs every
    location checked so users can diagnose discovery failures with -v.

    Returns:
        Path to the Chrome binary, or None if not found.
    """
    import glob as _glob
    import platform

    # --- Step 1: Check PATH via shutil.which ---
    path_binaries = [
        "google-chrome", "google-chrome-stable", "google-chrome-beta",
        "google-chrome-unstable", "chromium", "chromium-browser", "chrome",
    ]
    for binary in path_binaries:
        path = shutil.which(binary)
        if path:
            logger.debug("Found browser on PATH: %s -> %s", binary, path)
            return path
    logger.debug("No Chrome/Chromium found on PATH")

    # --- Step 2: Check well-known filesystem locations ---
    home = os.path.expanduser("~")
    system = platform.system()  # Linux, Darwin, Windows

    # Build a list of candidate paths per platform
    candidates = []

    # Linux standard packages (apt, yum, dnf, pacman, zypper)
    candidates += [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome-beta",
        "/usr/bin/google-chrome-unstable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/lib/chromium/chromium",
        "/usr/lib/chromium-browser/chromium-browser",
        "/usr/lib64/chromium-browser/chromium-browser",
    ]

    # Snap (Ubuntu default for Chromium since 19.10)
    candidates += [
        "/snap/bin/chromium",
        "/snap/chromium/current/usr/lib/chromium-browser/chrome",
    ]

    # Flatpak
    candidates += [
        "/var/lib/flatpak/exports/bin/com.google.Chrome",
        "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
        f"{home}/.local/share/flatpak/exports/bin/com.google.Chrome",
        f"{home}/.local/share/flatpak/exports/bin/org.chromium.Chromium",
    ]

    # Nix / NixOS
    candidates += [
        f"{home}/.nix-profile/bin/google-chrome-stable",
        f"{home}/.nix-profile/bin/chromium",
        "/run/current-system/sw/bin/google-chrome-stable",
        "/run/current-system/sw/bin/chromium",
    ]

    # macOS (native + Homebrew cask)
    candidates += [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        f"{home}/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        f"{home}/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/opt/homebrew/bin/chromium",
        "/usr/local/bin/chromium",
    ]

    # Windows (native + WSL mount points)
    candidates += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.getenv("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.getenv("PROGRAMFILES", ""), r"Google\Chrome\Application\chrome.exe"),
        # WSL: Windows Chrome accessible from Linux
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            logger.debug("Found browser at known path: %s", candidate)
            return candidate

    # --- Step 3: Glob search for Chrome in opt/local directories ---
    glob_patterns = [
        "/opt/google/chrome*/google-chrome*",
        "/opt/google/chrome*/chrome",
        "/opt/chromium*/chrome",
        f"{home}/.local/bin/google-chrome*",
        f"{home}/.local/bin/chromium*",
    ]
    for pattern in glob_patterns:
        matches = sorted(_glob.glob(pattern))
        for match in matches:
            if os.path.isfile(match) and os.access(match, os.X_OK):
                logger.debug("Found browser via glob: %s", match)
                return match

    # --- Step 4: Try platform-specific discovery commands ---
    if system == "Linux":
        # Ask the package manager where Chrome lives
        for cmd in [
            "dpkg -L google-chrome-stable 2>/dev/null | grep -m1 '/chrome$'",
            "rpm -ql google-chrome-stable 2>/dev/null | grep -m1 '/google-chrome'",
        ]:
            try:
                import subprocess
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=5,
                )
                path = result.stdout.strip()
                if path and os.path.isfile(path):
                    logger.debug("Found browser via package query: %s", path)
                    return path
            except Exception:
                continue

    elif system == "Darwin":
        # macOS: use mdfind (Spotlight) to locate Chrome.app
        try:
            import subprocess
            result = subprocess.run(
                ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
                capture_output=True, text=True, timeout=5,
            )
            for app_path in result.stdout.strip().splitlines():
                chrome_bin = os.path.join(app_path, "Contents", "MacOS", "Google Chrome")
                if os.path.isfile(chrome_bin):
                    logger.debug("Found browser via Spotlight: %s", chrome_bin)
                    return chrome_bin
        except Exception:
            pass

    logger.debug("Chrome/Chromium not found after exhaustive search")
    return None


def create_driver():
    """Create and configure a Chrome WebDriver instance with anti-detection measures.

    Raises:
        RuntimeError: If Chrome/Chromium is not installed.
        Exception: If WebDriver creation fails for other reasons.
    """
    # Validate Chrome is available before attempting driver creation
    chrome_path = validate_browser_installation()
    if not chrome_path:
        raise RuntimeError(
            "Chrome or Chromium could not be found.\n"
            "\n"
            "Troubleshooting (run with -v for detailed search log):\n"
            "  1. Verify it's installed:\n"
            "       which google-chrome || which chromium\n"
            "       google-chrome --version\n"
            "  2. If installed in a non-standard location, add it to PATH:\n"
            "       export PATH=\"/path/to/chrome/dir:$PATH\"\n"
            "  3. On Snap/Flatpak, ensure the binary is exported:\n"
            "       snap list chromium\n"
            "       flatpak list | grep -i chrom\n"
            "\n"
            "To install:\n"
            "  Ubuntu/Debian: sudo apt install google-chrome-stable\n"
            "  Fedora/RHEL:   sudo dnf install google-chrome-stable\n"
            "  Arch:          sudo pacman -S chromium\n"
            "  macOS:         brew install --cask google-chrome\n"
            "  Or download:   https://www.google.com/chrome/"
        )
    logger.info("Using browser: %s", chrome_path)

    options = Options()
    if config.HEADLESS:
        options.add_argument("--headless=new")

    # --- Core flags ---
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Realistic viewport (randomized from common resolutions to avoid fingerprinting)
    viewports = ["1920,1080", "1536,864", "1440,900", "1366,768", "1280,720"]
    options.add_argument(f"--window-size={random.choice(viewports)}")

    # --- Anti-detection: user agent ---
    # Rotate among recent Chrome versions on Windows/Mac
    ua_templates = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36",
    ]
    chrome_ver = random.choice(["130", "131", "132", "133", "134", "135"])
    user_agent = random.choice(ua_templates).format(ver=chrome_ver)
    options.add_argument(f"--user-agent={user_agent}")

    # --- Anti-detection: automation flags ---
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")

    # --- Anti-detection: additional stealth flags ---
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    # Accept language header for consistency
    options.add_argument("--lang=en-US")

    # --- Proxy support ---
    if config.PROXY_URL:
        proxy_url = config.PROXY_URL
        # Chrome's --proxy-server flag doesn't support embedded credentials.
        # For authenticated proxies, extract credentials and use an extension.
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        if parsed.username:
            # Authenticated proxy — install a tiny Chrome extension that
            # supplies credentials via the chrome.webRequest.onAuthRequired API.
            _add_proxy_auth_extension(options, parsed)
            # Build a URL without credentials for --proxy-server
            host_port = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
            scheme = parsed.scheme.replace("socks5", "socks5")  # passthrough
            proxy_url = f"{scheme}://{host_port}"

        options.add_argument(f"--proxy-server={proxy_url}")
        # Bypass proxy for localhost traffic
        options.add_argument("--proxy-bypass-list=localhost;127.0.0.1")
        logger.info("Using proxy: %s", proxy_url)

    try:
        # Selenium 4.6+ includes Selenium Manager which automatically
        # downloads and manages the correct chromedriver binary.
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        logger.error(
            "Failed to create Chrome WebDriver.\n"
            "  Error: %s\n"
            "  Browser found at: %s\n"
            "  Troubleshooting:\n"
            "    - Ensure chromedriver matches your Chrome version\n"
            "    - Try: pip install --upgrade selenium\n"
            "    - Check Chrome version: google-chrome --version",
            e, chrome_path,
        )
        raise

    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    # Note: implicitly_wait is intentionally not set. Mixing implicit and
    # explicit waits (WebDriverWait) leads to unpredictable timeout behavior.
    # All waits in this project use explicit WebDriverWait instead.

    # Inject stealth JavaScript via CDP (runs before any page JS)
    from scraper.human_behavior import setup_stealth_on_load
    setup_stealth_on_load(driver)

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
        if not isinstance(cookies, list):
            logger.debug("Invalid cookies file format (expected list)")
            return False
        # Must navigate to the domain first before adding cookies
        base = config.BASE_URL.rstrip("/")
        driver.get(base)
        time.sleep(2)
        loaded = 0
        for cookie in cookies:
            # Remove problematic fields that may differ across sessions
            cookie.pop("sameSite", None)
            cookie.pop("expiry", None)
            try:
                driver.add_cookie(cookie)
                loaded += 1
            except Exception:
                continue
        logger.debug("Loaded %d/%d cookies from %s", loaded, len(cookies), COOKIES_FILE)
        return loaded > 0
    except json.JSONDecodeError as e:
        logger.debug("Corrupt cookies file: %s", e)
        return False
    except OSError as e:
        logger.debug("Could not read cookies file: %s", e)
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
                _navigate_to_home(driver)
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
    """Fill and submit the CKL login form with human-like behavior."""
    from scraper.human_behavior import human_type, human_click, random_think_pause, random_micro_delay

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

        # Fill in credentials with human-like typing
        email_field.clear()
        random_micro_delay()
        human_type(email_field, config.USERNAME)
        random_think_pause()

        password_field.clear()
        random_micro_delay()
        human_type(password_field, config.PASSWORD)
        random_think_pause()

        # Find and click the "Log In" button with human-like behavior
        submit_btn = _find_login_button(driver)

        if submit_btn:
            human_click(driver, submit_btn, "Log In button")
        else:
            # Fallback: submit the form directly
            form = password_field.find_element(By.XPATH, "./ancestor::form")
            form.submit()

        # Wait for page to change (with jitter)
        time.sleep(3 + random.uniform(0.5, 2.0))

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

        # After login, the site may redirect to a tutorial/welcome page.
        # Navigate back to home to ensure we land on the practice sets grid.
        _navigate_to_home(driver)

        return True

    except Exception as e:
        logger.error("Login failed: %s", e)
        return False


def _navigate_to_home(driver):
    """Ensure we are on the home page (practice sets grid), not a tutorial page.

    After login, CKL may redirect to the 'Welcome to CKL' tutorial or another
    practice set page. This checks and clicks the HOME link if needed.
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        # Detect if we landed on a tutorial/practice set page instead of home
        on_tutorial = "Page" in body_text and " of " in body_text
        on_welcome = "Welcome to CKL" in body_text and "Getting Started" in body_text
        # Home page has the book cover grid with "Click the book image to launch"
        on_home = "click the book image" in body_text.lower()

        if (on_tutorial or on_welcome) and not on_home:
            logger.info("Detected tutorial/welcome page, navigating to HOME...")
            # Click the HOME link in the top nav bar
            try:
                home_link = driver.find_element(By.LINK_TEXT, "HOME")
                home_link.click()
                time.sleep(3)
                logger.info("Navigated to home page. URL: %s", driver.current_url)
            except Exception:
                # Fallback: navigate to base URL directly
                base = config.BASE_URL.rstrip("/")
                driver.get(base)
                time.sleep(3)
                logger.info("Navigated to base URL. URL: %s", driver.current_url)
    except Exception as e:
        logger.debug("Home navigation check failed: %s", e)


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
