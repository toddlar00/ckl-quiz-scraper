"""CKL quiz discovery and scraping logic.

CKL site structure:
  Home page (after login) → grid of Practice Sets (book covers)
  Practice Set page → table with chapters, each with "Launch" links
  Quiz page → one question at a time, "Question X of Y"
    - "Multiple Choice" label
    - Question text
    - Radio buttons A/B/C/D
    - "Submit" button → reveals correct answer + explanation
    - "Next Question" button to advance
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper import config

logger = logging.getLogger(__name__)

PROGRESS_FILE = ".ckl_progress.json"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class QuizQuestion:
    """A single quiz question with choices, correct answer, and explanation."""
    question_number: int
    total_questions: int
    question_type: str  # e.g. "Multiple Choice"
    question_text: str
    choices: list[dict] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    source_url: str = ""


@dataclass
class Chapter:
    """A chapter within a practice set containing quiz questions."""
    chapter_name: str
    launch_url: str
    status: str = ""  # "In Progress", "To Do", etc.
    questions: list[QuizQuestion] = field(default_factory=list)


@dataclass
class PracticeSet:
    """A practice set (book) containing chapters with questions."""
    title: str
    url: str
    chapters: list[Chapter] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Retry / wait helpers
# ---------------------------------------------------------------------------

def _retry(func, retries=3, delay=2, description="action"):
    """Retry a callable up to `retries` times with exponential backoff."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt < retries:
                wait = delay * attempt
                logger.warning(
                    "  %s failed (attempt %d/%d): %s — retrying in %ds",
                    description, attempt, retries, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "  %s failed after %d attempts: %s",
                    description, retries, e,
                )
    raise last_exc


def _safe_get(driver, url, description="page"):
    """Navigate to a URL with retry logic for transient network errors."""
    def _do_get():
        driver.get(url)
        # Wait for body to be present
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    _retry(_do_get, retries=3, delay=2, description=f"Loading {description}")
    time.sleep(2)


def _safe_click(driver, element, description="element"):
    """Click an element with fallback to JS click."""
    try:
        element.click()
    except WebDriverException:
        try:
            driver.execute_script("arguments[0].click();", element)
        except Exception as e:
            logger.warning("Could not click %s: %s", description, e)
            raise


# ---------------------------------------------------------------------------
# Progress tracking (resume support)
# ---------------------------------------------------------------------------

def _load_progress():
    """Load scraping progress from disk. Returns set of completed chapter URLs."""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_progress(data):
    """Save scraping progress to disk."""
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug("Could not save progress: %s", e)


def is_chapter_completed(chapter_url):
    """Check if a chapter was already scraped in a previous run."""
    progress = _load_progress()
    return chapter_url in progress.get("completed_chapters", {})


def mark_chapter_completed(chapter_url, question_count):
    """Mark a chapter as completed in the progress file."""
    progress = _load_progress()
    if "completed_chapters" not in progress:
        progress["completed_chapters"] = {}
    progress["completed_chapters"][chapter_url] = {
        "question_count": question_count,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_progress(progress)


def clear_progress():
    """Delete the progress file to start fresh."""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        logger.info("Progress file cleared")


# ---------------------------------------------------------------------------
# Practice set & chapter discovery
# ---------------------------------------------------------------------------

def discover_practice_sets(driver):
    """Find all Practice Sets on the home page after login.

    Returns list of (title, url) tuples.
    """
    base = config.BASE_URL.rstrip("/")
    _safe_get(driver, base, "home page")

    practice_sets = []

    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        seen_urls = set()

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                if not href or href == "#" or "javascript:" in href:
                    continue
                if href in seen_urls:
                    continue
                if not href.startswith(base):
                    continue

                text = link.text.strip().lower()
                skip_texts = [
                    "join a class", "get more practice sets", "home",
                    "help", "my account", "log out", "support",
                    "forgot", "create", "carolina academic",
                    "faculty", "archived", "expired",
                ]
                if any(s in text for s in skip_texts):
                    continue
                if not text and not link.find_elements(By.TAG_NAME, "img"):
                    continue

                title = link.text.strip()
                if not title:
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        title = parent.text.strip()
                    except Exception:
                        title = href

                if title and href != base + "/" and href != base:
                    seen_urls.add(href)
                    practice_sets.append((title, href))

            except StaleElementReferenceException:
                continue

    except Exception as e:
        logger.error("Error discovering practice sets: %s", e)
        from scraper.browser import diagnose_page
        diagnose_page(driver, "discover_practice_sets")

    # Deduplicate by URL
    unique = []
    seen = set()
    for title, url in practice_sets:
        if url not in seen:
            seen.add(url)
            unique.append((title, url))

    if not unique:
        logger.warning(
            "No practice sets found. Possible causes:\n"
            "  - Login may have failed silently\n"
            "  - Site layout may have changed\n"
            "  - No practice sets assigned to this account\n"
            "  Current URL: %s", driver.current_url,
        )
        from scraper.browser import diagnose_page
        diagnose_page(driver, "no_practice_sets")
    else:
        logger.info("Discovered %d practice set(s):", len(unique))
        for i, (title, url) in enumerate(unique, 1):
            logger.info("  %d. %s", i, title)

    return unique


def discover_chapters(driver, practice_set_url):
    """Navigate to a Practice Set and find all chapter "Launch" links.

    Returns list of Chapter objects.
    """
    _safe_get(driver, practice_set_url, "practice set")

    chapters = []

    try:
        launch_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Launch")

        if not launch_links:
            logger.warning(
                "No 'Launch' links found on practice set page.\n"
                "  The page may not have loaded fully, or the layout changed.\n"
                "  URL: %s", driver.current_url,
            )
            from scraper.browser import diagnose_page
            diagnose_page(driver, "no_launch_links")
            return chapters

        for launch_link in launch_links:
            try:
                href = launch_link.get_attribute("href") or ""
                if not href:
                    continue

                row = launch_link.find_element(By.XPATH, "./ancestor::tr")
                cells = row.find_elements(By.TAG_NAME, "td")

                chapter_name = ""
                status = ""

                for cell in cells:
                    cell_text = cell.text.strip()
                    if cell_text.startswith("Chapter") or ":" in cell_text:
                        if len(cell_text) > 5 and cell_text != "Launch":
                            chapter_name = cell_text
                    if cell_text in ("To Do", "In Progress", "Complete", "Completed"):
                        status = cell_text

                if not chapter_name:
                    row_text = row.text.strip()
                    chapter_name = row_text.replace("Launch", "").strip()

                chapters.append(Chapter(
                    chapter_name=chapter_name,
                    launch_url=href,
                    status=status,
                ))

            except (StaleElementReferenceException, NoSuchElementException):
                continue

    except Exception as e:
        logger.error("Error discovering chapters: %s", e)

    logger.info("Found %d chapter(s):", len(chapters))
    for ch in chapters:
        logger.info("  - %s [%s]", ch.chapter_name, ch.status)

    return chapters


# ---------------------------------------------------------------------------
# Question scraping
# ---------------------------------------------------------------------------

def scrape_chapter_questions(driver, chapter, resume=True):
    """Scrape all questions from a chapter by launching it and iterating.

    Args:
        driver: Selenium WebDriver instance.
        chapter: Chapter object to populate with questions.
        resume: If True, skip chapters that were already scraped.

    Returns:
        List of QuizQuestion objects (also stored in chapter.questions).
    """
    # Check if already completed in a previous run
    if resume and is_chapter_completed(chapter.launch_url):
        logger.info("  Skipping (already scraped in previous run)")
        return chapter.questions

    _safe_get(driver, chapter.launch_url, f"chapter: {chapter.chapter_name}")

    questions = []

    total = _get_total_questions(driver)
    logger.info("  %s question(s) to scrape", total or "Unknown number of")

    question_num = 0
    max_questions = total or 200
    consecutive_failures = 0

    while question_num < max_questions:
        question_num += 1

        try:
            q = _scrape_single_question(driver, question_num, total or 0)
            if q:
                questions.append(q)
                consecutive_failures = 0
                logger.info(
                    "  [%d/%s] %s → Answer: %s",
                    q.question_number,
                    total or "?",
                    q.question_text[:70] + ("..." if len(q.question_text) > 70 else ""),
                    q.correct_answer or "unknown",
                )
            else:
                consecutive_failures += 1
                logger.warning("  Could not parse question %d", question_num)
                from scraper.browser import diagnose_page
                diagnose_page(driver, f"parse_fail_q{question_num}")

            # Too many consecutive failures → something is wrong
            if consecutive_failures >= 3:
                logger.error(
                    "  3 consecutive failures — stopping chapter scrape.\n"
                    "  This may indicate the page structure changed."
                )
                from scraper.browser import diagnose_page
                diagnose_page(driver, "consecutive_failures")
                break

            # Try to go to next question
            if not _click_next_question(driver):
                logger.info("  Finished chapter (%d questions scraped)", len(questions))
                break

            # Rate limiting — small pause between questions
            time.sleep(config.REQUEST_DELAY)

        except Exception as e:
            consecutive_failures += 1
            logger.warning("  Error on question %d: %s", question_num, e)
            if not _click_next_question(driver):
                break

    chapter.questions = questions
    mark_chapter_completed(chapter.launch_url, len(questions))
    return questions


def _get_total_questions(driver):
    """Extract total question count from 'Question X of Y' text."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        match = re.search(r'Question\s+\d+\s+of\s+(\d+)', body_text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    try:
        page = driver.page_source
        match = re.search(r'(\d+)\s+of\s+(\d+)', page)
        if match:
            return int(match.group(2))
    except Exception:
        pass
    return None


def _scrape_single_question(driver, question_num, total):
    """Scrape one question: read it, submit an answer, read the feedback."""
    source_url = driver.current_url

    # Detect question type
    question_type = _detect_question_type(driver)

    # Extract question text
    question_text = _extract_question_text(driver)
    if not question_text:
        return None

    # Extract answer choices
    choices = _extract_choices(driver)

    # Submit answer to reveal correct answer + explanation
    _submit_answer(driver)
    time.sleep(2)

    # Read feedback
    correct_answer, explanation = _extract_feedback(driver)

    # Mark the correct choice
    for choice in choices:
        if correct_answer and choice["label"] == correct_answer:
            choice["is_correct"] = True

    return QuizQuestion(
        question_number=question_num,
        total_questions=total,
        question_type=question_type,
        question_text=question_text,
        choices=choices,
        correct_answer=correct_answer,
        explanation=explanation,
        source_url=source_url,
    )


def _detect_question_type(driver):
    """Detect the question type from page text."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "Multiple Choice" in body_text:
            return "Multiple Choice"
        if "True/False" in body_text or "True or False" in body_text:
            return "True/False"
        if "Fill in" in body_text:
            return "Fill in the Blank"
        if "Select all" in body_text or "select all" in body_text:
            return "Select All That Apply"
    except Exception:
        pass
    return ""


def _extract_question_text(driver):
    """Extract the question text between the header and answer choices."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Remove everything before the question marker
        marker = ">>>> Question <<<<"
        if marker in body_text:
            body_text = body_text.split(marker, 1)[1].strip()

        lines = body_text.split("\n")
        question_lines = []
        for line in lines:
            stripped = line.strip()
            # Stop when we hit an answer choice
            if re.match(r'^[○●]?\s*[A-D]\.\s', stripped):
                break
            if not question_lines and not stripped:
                continue
            # Skip type labels
            if stripped in ("Multiple Choice", "True/False", "Fill in the Blank",
                            "Select All That Apply"):
                continue
            question_lines.append(stripped)

        question_text = " ".join(question_lines).strip()
        question_text = re.sub(r'\s+', ' ', question_text)
        return question_text

    except Exception as e:
        logger.debug("Error extracting question text: %s", e)
        return ""


def _extract_choices(driver):
    """Extract answer choices (A, B, C, D) from radio buttons."""
    choices = []

    try:
        radio_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")

        for radio in radio_inputs:
            try:
                radio_id = radio.get_attribute("id")
                label = None

                if radio_id:
                    labels = driver.find_elements(
                        By.CSS_SELECTOR, f"label[for='{radio_id}']"
                    )
                    if labels:
                        label = labels[0]

                if not label:
                    try:
                        label = radio.find_element(By.XPATH, "./ancestor::label")
                    except NoSuchElementException:
                        try:
                            label = radio.find_element(By.XPATH, "./following-sibling::label")
                        except NoSuchElementException:
                            pass

                label_text = (label.text.strip() if label
                              else radio.find_element(By.XPATH, "./..").text.strip())

                if not label_text:
                    continue

                match = re.match(r'^([A-D])\.\s*(.*)', label_text, re.DOTALL)
                if match:
                    letter = match.group(1)
                    text = match.group(2).strip()
                else:
                    letter = chr(65 + len(choices))
                    text = label_text

                choices.append({
                    "label": letter,
                    "text": text,
                    "is_correct": False,
                })

            except (StaleElementReferenceException, NoSuchElementException):
                continue

    except Exception as e:
        logger.debug("Error extracting choices from radio buttons: %s", e)

    # Fallback: parse from page text
    if not choices:
        choices = _extract_choices_from_text(driver)

    if not choices:
        logger.warning("  No answer choices found on page")

    return choices


def _extract_choices_from_text(driver):
    """Fallback: extract choices from page text using regex."""
    choices = []
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        pattern = re.compile(
            r'([A-D])\.\s+(.+?)(?=\n\s*[A-D]\.\s|\nSubmit|\Z)', re.DOTALL
        )
        matches = pattern.findall(body_text)

        for label, text in matches:
            text = text.strip()
            if text and len(text) > 1:
                choices.append({
                    "label": label,
                    "text": re.sub(r'\s+', ' ', text),
                    "is_correct": False,
                })
    except Exception:
        pass
    return choices


def _submit_answer(driver):
    """Select an answer and click Submit to reveal the feedback."""
    try:
        # Select the first available radio button
        radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        for radio in radios:
            if radio.is_displayed() and radio.is_enabled():
                _safe_click(driver, radio, "radio button")
                break

        time.sleep(1)

        # Find Submit button
        submit_btn = _find_button(driver, ["submit"])
        if submit_btn:
            _safe_click(driver, submit_btn, "Submit button")
            time.sleep(2)
        else:
            logger.warning("  Could not find Submit button")
            from scraper.browser import diagnose_page
            diagnose_page(driver, "no_submit_button")

    except Exception as e:
        logger.warning("  Error submitting answer: %s", e)


def _find_button(driver, text_matches):
    """Find a visible button matching any of the given text strings."""
    text_matches_lower = [t.lower() for t in text_matches]

    # input[type='submit'] and button[type='submit']
    for selector in ["input[type='submit']", "button[type='submit']"]:
        for btn in driver.find_elements(By.CSS_SELECTOR, selector):
            if btn.is_displayed():
                btn_text = (btn.text or btn.get_attribute("value") or "").strip().lower()
                if any(t in btn_text for t in text_matches_lower) or not btn_text:
                    return btn

    # Generic buttons by text
    for btn in driver.find_elements(By.CSS_SELECTOR, "button, input[type='button']"):
        btn_text = (btn.text or btn.get_attribute("value") or "").strip().lower()
        if any(t == btn_text for t in text_matches_lower):
            if btn.is_displayed():
                return btn

    return None


def _extract_feedback(driver):
    """Extract the correct answer and explanation from post-submit feedback."""
    correct_answer = ""
    explanation = ""

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # "The correct answer is C."
        match = re.search(
            r'The correct answer is\s+([A-D])',
            body_text,
            re.IGNORECASE,
        )
        if match:
            correct_answer = match.group(1).upper()

        # If we got it right, "Correct!" appears without "incorrect"
        if not correct_answer:
            if re.search(r'\bCorrect[!.]', body_text) and "incorrect" not in body_text.lower():
                correct_answer = "A"  # We always select A

        # "Here's Why:" explanation
        heres_why_match = re.search(
            r"Here'?s\s+Why:?\s*(.+?)(?=Check this box|You will be able|I'm still confused|Next Question|Back to Practice|$)",
            body_text,
            re.DOTALL | re.IGNORECASE,
        )
        if heres_why_match:
            explanation = heres_why_match.group(1).strip()
            explanation = re.sub(r'\n\s*\n', '\n', explanation).strip()

        if not correct_answer:
            logger.warning("  Could not determine correct answer from feedback")

    except Exception as e:
        logger.debug("Error extracting feedback: %s", e)

    return correct_answer, explanation


def _click_next_question(driver):
    """Click the 'Next Question' button. Returns True if successful."""
    try:
        # Try partial link text first (most reliable)
        try:
            next_link = driver.find_element(By.PARTIAL_LINK_TEXT, "Next Question")
            if next_link.is_displayed():
                _safe_click(driver, next_link, "Next Question")
                time.sleep(3)
                return True
        except NoSuchElementException:
            pass

        # Try XPath for any clickable element with "Next Question"
        try:
            next_el = driver.find_element(
                By.XPATH, "//*[contains(text(), 'Next Question')]"
            )
            if next_el.is_displayed():
                _safe_click(driver, next_el, "Next Question")
                time.sleep(3)
                return True
        except NoSuchElementException:
            pass

        # Broader search across buttons and links
        for el in driver.find_elements(By.CSS_SELECTOR, "a, button"):
            try:
                text = (el.text or el.get_attribute("value") or "").strip()
                if "next question" in text.lower() and el.is_displayed():
                    _safe_click(driver, el, "Next Question")
                    time.sleep(3)
                    return True
            except StaleElementReferenceException:
                continue

    except Exception as e:
        logger.debug("Error clicking Next Question: %s", e)

    return False
