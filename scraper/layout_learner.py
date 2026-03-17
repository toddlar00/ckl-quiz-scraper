"""Website layout learner — probes site structure and learns page patterns.

Analyzes a quiz website to identify:
  - Page structure (DOM selectors for questions, choices, feedback)
  - Question types present (multiple choice, true/false, fill-in, etc.)
  - Navigation patterns (next button, submit button, preamble pages)

This module builds a LayoutProfile by sampling pages and extracting
repeating structural patterns, which the scraper then uses for more
reliable extraction.
"""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)

# Where to persist learned layouts
LAYOUT_CACHE_FILE = ".ckl_layout_cache.json"

# Question types we recognize
MULTIPLE_CHOICE_TYPES = {"Multiple Choice", "True/False"}
NON_MC_TYPES = {"Fill in the Blank", "Select All That Apply", "Essay", "Short Answer"}
ALL_KNOWN_TYPES = MULTIPLE_CHOICE_TYPES | NON_MC_TYPES


@dataclass
class PageSignature:
    """Structural fingerprint of a single quiz page."""
    has_radio_buttons: bool = False
    has_checkboxes: bool = False
    has_text_input: bool = False
    has_textarea: bool = False
    radio_count: int = 0
    checkbox_count: int = 0
    has_submit_button: bool = False
    has_next_button: bool = False
    detected_type: str = ""
    question_marker_found: bool = False
    choice_labels_found: list = field(default_factory=list)


@dataclass
class LayoutProfile:
    """Learned structural profile of a quiz website.

    Built by sampling multiple pages and extracting common patterns.
    Used to make scraping decisions (e.g., skip non-MC questions).
    """
    site_name: str = ""
    pages_sampled: int = 0

    # Selectors that reliably find elements
    question_container_selector: str = ""
    choice_selector: str = ""
    submit_selector: str = ""
    next_selector: str = ""
    feedback_selector: str = ""

    # Question type indicators found in page text
    type_indicators: dict = field(default_factory=dict)

    # Structural patterns
    uses_radio_for_mc: bool = True
    uses_checkboxes_for_multi: bool = False
    uses_text_input_for_fill: bool = False
    has_preamble_pages: bool = False

    # Question type distribution (from sampled pages)
    type_counts: dict = field(default_factory=dict)

    # Multiple choice detection patterns
    mc_indicators: list = field(default_factory=list)
    non_mc_indicators: list = field(default_factory=list)

    def is_multiple_choice_page(self, body_text, page_sig=None):
        """Determine if the current page contains a multiple-choice question.

        Uses learned patterns to classify the page. Returns True for
        standard multiple choice and true/false questions (both use
        radio buttons with fixed choices).

        Args:
            body_text: Full text content of the page.
            page_sig: Optional pre-computed PageSignature.

        Returns:
            True if the page is a multiple-choice question.
        """
        # Check explicit type indicators in text
        detected = detect_question_type(body_text)
        if detected in MULTIPLE_CHOICE_TYPES:
            return True
        if detected in NON_MC_TYPES:
            return False

        # Use structural signals from page signature
        if page_sig:
            # Radio buttons with 2-6 options = likely MC
            if page_sig.has_radio_buttons and 2 <= page_sig.radio_count <= 6:
                return True
            # Text input or textarea = likely fill-in or essay
            if page_sig.has_text_input or page_sig.has_textarea:
                return False
            # Checkboxes = likely select-all
            if page_sig.has_checkboxes and not page_sig.has_radio_buttons:
                return False

        # Text-based heuristics
        if page_sig and page_sig.has_radio_buttons:
            return True

        # Check for choice patterns (A. B. C. D.)
        if re.search(r'^[A-D]\.\s', body_text, re.MULTILINE):
            return True

        # Default: if we can't tell, assume MC (safer to include than exclude)
        return True

    def save(self, path=None):
        """Persist the layout profile to disk."""
        path = path or LAYOUT_CACHE_FILE
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        logger.debug("Layout profile saved to %s", path)

    @classmethod
    def load(cls, path=None):
        """Load a previously saved layout profile."""
        path = path or LAYOUT_CACHE_FILE
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            profile = cls(**{k: v for k, v in data.items()
                            if k in cls.__dataclass_fields__})
            logger.debug("Loaded layout profile from %s (%d pages sampled)",
                        path, profile.pages_sampled)
            return profile
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Could not load layout cache: %s", e)
            return None


def detect_question_type(body_text):
    """Detect question type from page text keywords.

    Returns:
        Question type string, or empty string if unknown.
    """
    if "Multiple Choice" in body_text:
        return "Multiple Choice"
    if "True/False" in body_text or "True or False" in body_text:
        return "True/False"
    if "Fill in" in body_text:
        return "Fill in the Blank"
    if "Select all" in body_text or "select all" in body_text:
        return "Select All That Apply"
    if "Essay" in body_text:
        return "Essay"
    if "Short Answer" in body_text:
        return "Short Answer"
    return ""


def analyze_page(driver):
    """Analyze the current page and return a PageSignature.

    Examines DOM elements and page text to fingerprint the page structure.

    Args:
        driver: Selenium WebDriver on the page to analyze.

    Returns:
        PageSignature describing the page structure.
    """
    sig = PageSignature()

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return sig

    # Detect question type from text
    sig.detected_type = detect_question_type(body_text)
    sig.question_marker_found = ">>>> Question <<<<" in body_text

    # Check for radio buttons (MC / True-False)
    try:
        radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        sig.has_radio_buttons = len(radios) > 0
        sig.radio_count = len(radios)
    except Exception:
        pass

    # Check for checkboxes (Select All That Apply)
    try:
        checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        sig.has_checkboxes = len(checkboxes) > 0
        sig.checkbox_count = len(checkboxes)
    except Exception:
        pass

    # Check for text inputs (Fill in the Blank)
    try:
        text_inputs = driver.find_elements(By.CSS_SELECTOR,
            "input[type='text']:not([name*='search']):not([name*='filter'])")
        sig.has_text_input = len(text_inputs) > 0
    except Exception:
        pass

    # Check for textareas (Essay / Short Answer)
    try:
        textareas = driver.find_elements(By.CSS_SELECTOR, "textarea")
        sig.has_textarea = len(textareas) > 0
    except Exception:
        pass

    # Check for Submit button
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], a"):
            text = (el.text or el.get_attribute("value") or "").strip().lower()
            if "submit" in text:
                sig.has_submit_button = True
                break
    except Exception:
        pass

    # Check for Next Question button/link
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, "a, button"):
            text = (el.text or "").strip().lower()
            if "next question" in text:
                sig.has_next_button = True
                break
    except Exception:
        pass

    # Check for choice label patterns
    choice_labels = re.findall(r'^([A-D])\.\s', body_text, re.MULTILINE)
    sig.choice_labels_found = sorted(set(choice_labels))

    return sig


def learn_layout(driver, site_scraper, max_sample_pages=5):
    """Learn the website layout by sampling quiz pages.

    Navigates through a few questions to build a LayoutProfile describing
    the site's structure. This profile is cached for future runs.

    Args:
        driver: Selenium WebDriver (logged in, on a quiz page).
        site_scraper: The BaseScraper instance (for navigation methods).
        max_sample_pages: Number of pages to sample.

    Returns:
        LayoutProfile with learned patterns.
    """
    # Try loading cached profile first
    cached = LayoutProfile.load()
    if cached and cached.pages_sampled >= max_sample_pages:
        logger.info("Using cached layout profile (%d pages previously sampled)",
                    cached.pages_sampled)
        return cached

    profile = LayoutProfile(site_name=site_scraper.SITE_NAME)

    logger.info("Learning website layout (sampling up to %d pages)...", max_sample_pages)

    for i in range(max_sample_pages):
        sig = analyze_page(driver)
        profile.pages_sampled += 1

        # Track question type distribution
        qtype = sig.detected_type or "Unknown"
        profile.type_counts[qtype] = profile.type_counts.get(qtype, 0) + 1

        # Learn structural patterns
        if sig.has_radio_buttons:
            profile.uses_radio_for_mc = True
        if sig.has_checkboxes:
            profile.uses_checkboxes_for_multi = True
        if sig.has_text_input:
            profile.uses_text_input_for_fill = True

        # Learn selectors from DOM
        if not profile.choice_selector and sig.has_radio_buttons:
            profile.choice_selector = "input[type='radio']"
        if not profile.choice_selector and sig.has_checkboxes:
            profile.choice_selector = "input[type='checkbox']"

        _learn_selectors(driver, profile)

        logger.debug("  Page %d: type=%s, radios=%d, checkboxes=%d",
                     i + 1, qtype, sig.radio_count, sig.checkbox_count)

        # Try to advance to next page (submit + next)
        try:
            site_scraper.submit_answer()
            if not site_scraper.click_next_question():
                logger.debug("  Could not advance past page %d", i + 1)
                break
        except Exception:
            break

    # Build MC/non-MC indicator lists from observed patterns
    for qtype, count in profile.type_counts.items():
        if qtype in MULTIPLE_CHOICE_TYPES:
            profile.mc_indicators.append(qtype)
        elif qtype in NON_MC_TYPES:
            profile.non_mc_indicators.append(qtype)

    profile.save()
    logger.info("Layout learning complete: %d pages sampled, types found: %s",
                profile.pages_sampled, dict(profile.type_counts))

    return profile


def _learn_selectors(driver, profile):
    """Try to discover reliable CSS selectors for key page elements."""
    # Learn submit button selector
    if not profile.submit_selector:
        for selector in [
            "input[type='submit']",
            "button[type='submit']",
            "input[value*='Submit' i]",
            "button:has-text('Submit')",
        ]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                if els:
                    profile.submit_selector = selector
                    break
            except Exception:
                continue

    # Learn feedback container selector
    if not profile.feedback_selector:
        for selector in [
            ".feedback",
            ".answer-feedback",
            "[class*='feedback']",
            "[class*='explanation']",
            "[class*='result']",
        ]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                if els:
                    profile.feedback_selector = selector
                    break
            except Exception:
                continue


def is_multiple_choice_question(driver, body_text, profile=None):
    """Quick check: is the current page a multiple-choice question?

    Convenience function that combines text-based and structural analysis.
    If a LayoutProfile is provided, uses learned patterns for better accuracy.

    Args:
        driver: Selenium WebDriver on the question page.
        body_text: Cached page text.
        profile: Optional LayoutProfile for learned pattern matching.

    Returns:
        True if the question is multiple choice or true/false.
    """
    # Fast path: explicit type in text
    detected = detect_question_type(body_text)
    if detected in MULTIPLE_CHOICE_TYPES:
        return True
    if detected in NON_MC_TYPES:
        return False

    # Structural analysis
    sig = analyze_page(driver)

    if profile:
        return profile.is_multiple_choice_page(body_text, sig)

    # No profile — use basic heuristics
    if sig.has_radio_buttons and 2 <= sig.radio_count <= 6:
        return True
    if sig.has_text_input or sig.has_textarea:
        return False
    if sig.has_checkboxes and not sig.has_radio_buttons:
        return False

    # Check for A. B. C. D. pattern
    if re.search(r'^[A-D]\.\s', body_text, re.MULTILINE):
        return True

    return True  # Default to including
