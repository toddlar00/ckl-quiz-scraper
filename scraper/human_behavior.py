"""Human-like behavior simulation to avoid bot detection.

Provides realistic typing, mouse movement, scrolling, and timing
to make Selenium interactions appear natural to anti-bot systems.

Timing profiles can be configured via environment variables:
  HUMAN_TYPING_MIN=0.03   Minimum delay between keystrokes (seconds)
  HUMAN_TYPING_MAX=0.15   Maximum delay between keystrokes (seconds)
  HUMAN_THINK_MIN=0.5     Minimum thinking pause (seconds)
  HUMAN_THINK_MAX=2.5     Maximum thinking pause (seconds)
  HUMAN_SCROLL_CHANCE=0.2 Probability of random scroll per question (0-1)
"""

import logging
import os
import random
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable timing profiles
# ---------------------------------------------------------------------------

TYPING_MIN_DELAY = float(os.getenv("HUMAN_TYPING_MIN", "0.03"))
TYPING_MAX_DELAY = float(os.getenv("HUMAN_TYPING_MAX", "0.15"))
THINK_MIN = float(os.getenv("HUMAN_THINK_MIN", "0.5"))
THINK_MAX = float(os.getenv("HUMAN_THINK_MAX", "2.5"))
SCROLL_CHANCE = float(os.getenv("HUMAN_SCROLL_CHANCE", "0.2"))


# ---------------------------------------------------------------------------
# Randomized timing
# ---------------------------------------------------------------------------

def human_delay(base_seconds, jitter_ratio=0.5):
    """Sleep for a human-like duration with random jitter.

    Adds gaussian jitter around the base value so delays aren't uniform.
    E.g., base=2.0, jitter_ratio=0.5 -> sleeps between ~1.0 and ~3.0 seconds.
    """
    if base_seconds <= 0:
        return
    jitter = random.gauss(0, base_seconds * jitter_ratio * 0.5)
    duration = max(0.1, base_seconds + jitter)
    time.sleep(duration)


def random_micro_delay():
    """Tiny random pause (50-300ms) to simulate human reaction time."""
    time.sleep(random.uniform(0.05, 0.3))


def random_think_pause():
    """Simulate a human reading/thinking pause (configurable range)."""
    time.sleep(random.uniform(THINK_MIN, THINK_MAX))


# ---------------------------------------------------------------------------
# Human-like typing
# ---------------------------------------------------------------------------

def human_type(element, text, min_delay=None, max_delay=None):
    """Type text character by character with natural inter-key timing.

    Simulates human typing speed with:
      - Variable delay between keystrokes
      - Occasional brief pauses (as if thinking)
      - Slightly faster for common sequences
      - Occasional burst speed for familiar words

    Args:
        element: Selenium WebElement to type into.
        text: String to type.
        min_delay: Minimum keystroke delay (default from config).
        max_delay: Maximum keystroke delay (default from config).
    """
    min_delay = min_delay or TYPING_MIN_DELAY
    max_delay = max_delay or TYPING_MAX_DELAY

    for i, char in enumerate(text):
        element.send_keys(char)

        # Base delay between keystrokes
        delay = random.uniform(min_delay, max_delay)

        # Occasional longer pause (simulates thinking or looking at screen)
        if random.random() < 0.05:
            delay += random.uniform(0.2, 0.6)

        # Slightly faster after common sequences (muscle memory)
        if i > 0 and text[i - 1:i + 1].lower() in ("th", "he", "in", "er", "an", "re", "on"):
            delay *= 0.6

        # Brief pause after spaces (word boundary)
        if char == " " and random.random() < 0.15:
            delay += random.uniform(0.1, 0.3)

        time.sleep(delay)


# ---------------------------------------------------------------------------
# Human-like mouse movement
# ---------------------------------------------------------------------------

def human_move_to(driver, element):
    """Move the mouse to an element with a natural, slightly curved path.

    Uses multiple intermediate points with small random offsets to
    simulate natural hand movement rather than teleporting.
    """
    try:
        actions = ActionChains(driver)

        # Get element location and size for offset randomization
        size = element.size
        # Click slightly off-center (humans don't click dead center)
        x_offset = random.randint(-max(1, size["width"] // 6), max(1, size["width"] // 6))
        y_offset = random.randint(-max(1, size["height"] // 6), max(1, size["height"] // 6))

        # Move with small intermediate pauses
        actions.move_to_element_with_offset(element, x_offset, y_offset)
        actions.pause(random.uniform(0.05, 0.15))
        actions.perform()
    except Exception:
        # Fallback: simple move without offset
        try:
            ActionChains(driver).move_to_element(element).perform()
        except Exception:
            pass  # Element may not be interactable for mouse move


def human_click(driver, element, description="element"):
    """Click an element with human-like behavior.

    Moves to the element first, pauses briefly, then clicks.
    Falls back to JS click if native click fails.
    """
    try:
        # Scroll element into view first
        human_scroll_to_element(driver, element)
        random_micro_delay()

        # Move mouse to element
        human_move_to(driver, element)
        random_micro_delay()

        # Click
        element.click()
    except Exception:
        try:
            # JS click fallback
            driver.execute_script("arguments[0].click();", element)
        except Exception as e:
            logger.warning("Could not click %s: %s", description, e)
            raise


# ---------------------------------------------------------------------------
# Scrolling behavior
# ---------------------------------------------------------------------------

def human_scroll_to_element(driver, element):
    """Scroll an element into view with smooth, natural scrolling."""
    try:
        # Check if element is in viewport
        in_viewport = driver.execute_script("""
            var rect = arguments[0].getBoundingClientRect();
            return (rect.top >= 0 && rect.bottom <= window.innerHeight);
        """, element)

        if not in_viewport:
            # Smooth scroll with slight offset (humans don't scroll to exact pixel)
            driver.execute_script("""
                arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});
            """, element)
            time.sleep(random.uniform(0.3, 0.7))
    except Exception:
        pass


def random_scroll(driver):
    """Scroll the page slightly to simulate human reading behavior.

    Simulates natural reading patterns:
      - Small scrolls (reading next paragraph)
      - Occasional scroll-back (re-reading)
      - Variable scroll speeds
    """
    try:
        # Vary scroll amount — sometimes small, sometimes larger
        if random.random() < 0.7:
            # Small scroll (reading next paragraph)
            scroll_amount = random.randint(80, 250)
        else:
            # Larger scroll (skimming)
            scroll_amount = random.randint(250, 500)

        if random.random() < 0.25:
            scroll_amount = -scroll_amount  # Scroll back up to re-read

        driver.execute_script(f"window.scrollBy({{top: {scroll_amount}, behavior: 'smooth'}});")
        time.sleep(random.uniform(0.3, 0.8))
    except Exception:
        pass


def should_scroll():
    """Decide whether to perform a random scroll this iteration.

    Returns True with probability SCROLL_CHANCE (default 20%).
    """
    return random.random() < SCROLL_CHANCE


# ---------------------------------------------------------------------------
# Browser stealth — JavaScript patches
# ---------------------------------------------------------------------------

STEALTH_JS = """
// Override navigator.webdriver to be undefined
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// Override navigator.plugins to look real
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ];
        plugins.length = 3;
        return plugins;
    },
    configurable: true,
});

// Override navigator.languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
});

// Override navigator.platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
    configurable: true,
});

// Fix chrome.runtime to look real
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
    };
}

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Mask headless indicators in WebGL
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // Vendor
    if (parameter === 37445) return 'Google Inc. (NVIDIA)';
    // Renderer
    if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return getParameter.call(this, parameter);
};
"""


def inject_stealth(driver):
    """Inject stealth JavaScript to hide automation markers.

    Should be called after every page navigation to re-apply patches,
    since navigations reset the page's JS context.
    """
    try:
        driver.execute_script(STEALTH_JS)
    except Exception as e:
        logger.debug("Stealth injection failed: %s", e)


def setup_stealth_on_load(driver):
    """Configure Chrome DevTools Protocol to inject stealth JS on every page load.

    This uses the Page.addScriptToEvaluateOnNewDocument CDP command to ensure
    stealth patches are applied before any site JS runs.
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": STEALTH_JS,
        })
        logger.debug("Stealth CDP injection configured")
    except Exception as e:
        logger.debug("CDP stealth setup failed (non-critical): %s", e)
