"""CKL quiz discovery and scraping logic.

CKL site structure:
  Home page (after login) -> grid of Practice Sets (book covers)
  Practice Set page -> table with chapters, each with "Launch" links
  Quiz page -> one question at a time, "Question X of Y"
    - "Multiple Choice" label
    - Question text
    - Radio buttons A/B/C/D
    - "Submit" button -> reveals correct answer + explanation
    - "Next Question" button to advance

Module Organization:
  - scraper.models: QuizQuestion, Chapter, PracticeSet dataclasses
  - scraper.adaptive_delay: AdaptiveDelay throttling system
  - scraper.progress: Resume/checkpoint support
  - scraper.quiz_scraper: Discovery, extraction, and scraping orchestration
"""

import logging
import re
import time

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
from scraper.shutdown import shutdown_requested

# Re-export from new modules for backward compatibility
from scraper.models import QuizQuestion, Chapter, PracticeSet, validate_practice_sets  # noqa: F401
from scraper.adaptive_delay import (  # noqa: F401
    AdaptiveDelay,
    DEFAULT_DELAY_BUDGET,
    DELAY_FRACTIONS,
    ADAPTIVE_DELAY_FILE,
    get_adaptive_delay,
    reset_adaptive_delay,
)
from scraper.progress import (  # noqa: F401
    PROGRESS_FILE,
    is_chapter_completed,
    mark_chapter_completed,
    save_chapter_checkpoint,
    load_chapter_checkpoint,
    clear_progress,
)

logger = logging.getLogger(__name__)


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
    """Navigate to a URL with retry logic, stealth re-injection, and HTTP error detection."""
    def _do_get():
        driver.get(url)
        # Wait for body to be present and page to finish loading
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Wait for document.readyState == "complete" instead of hardcoded sleep
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        # Check for HTTP error pages (rate limiting, server errors)
        _check_http_errors(driver, url)
        # Re-inject stealth JS after navigation (page context resets)
        from scraper.human_behavior import inject_stealth
        inject_stealth(driver)
    _retry(_do_get, retries=3, delay=2, description=f"Loading {description}")


def _check_http_errors(driver, url):
    """Detect HTTP error pages and raise appropriate exceptions.

    Checks for 429 Too Many Requests, 403 Forbidden, and 5xx errors
    that may appear as error pages after navigation.
    """
    try:
        title = driver.title.lower()
        body_text = driver.find_element(By.TAG_NAME, "body").text[:500].lower()
        combined = f"{title} {body_text}"

        if "429" in combined or "too many requests" in combined or "rate limit" in combined:
            logger.warning("Rate limited (429) at %s — backing off", url)
            # Exponential backoff for rate limiting
            delay = get_adaptive_delay()
            delay.on_failure()
            delay.on_failure()  # Double penalty for rate limiting
            raise WebDriverException(f"HTTP 429 Too Many Requests at {url}")

        if "403" in title and "forbidden" in combined:
            logger.warning("Access forbidden (403) at %s", url)
            raise WebDriverException(f"HTTP 403 Forbidden at {url}")

        if any(code in title for code in ("500", "502", "503", "504")):
            logger.warning("Server error at %s: %s", url, title)
            raise WebDriverException(f"Server error at {url}: {title}")

    except WebDriverException:
        raise
    except Exception:
        pass  # Body text extraction failed — not an error page


def _safe_click(driver, element, description="element"):
    """Click an element with human-like behavior and fallback to JS click."""
    from scraper.human_behavior import human_click
    try:
        human_click(driver, element, description)
    except Exception as e:
        logger.warning("Could not click %s: %s", description, e)
        raise


# ---------------------------------------------------------------------------
# Practice set & chapter discovery
# ---------------------------------------------------------------------------

def discover_practice_sets(driver):
    """Find all Practice Sets on the home page after login.

    Returns list of (title, url) tuples.
    """
    base = config.BASE_URL.rstrip("/")
    _safe_get(driver, base, "home page")

    # If we landed on a tutorial/welcome page instead of the home grid,
    # click the HOME nav link to get to the practice sets grid.
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "Getting Started" in body_text and "Page" in body_text and "of" in body_text:
            logger.info("Detected tutorial page, clicking HOME link...")
            home_link = driver.find_element(By.LINK_TEXT, "HOME")
            home_link.click()
            time.sleep(3)
    except Exception:
        pass

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
                    "welcome to ckl", "getting started",
                    "show", "search",
                ]
                if any(s in text for s in skip_texts):
                    continue
                if not text and not link.find_elements(By.TAG_NAME, "img"):
                    continue

                title = link.text.strip()
                if not title:
                    # Try image alt text (book covers are often img links)
                    try:
                        imgs = link.find_elements(By.TAG_NAME, "img")
                        for img in imgs:
                            alt = (img.get_attribute("alt") or "").strip()
                            if alt:
                                title = alt
                                break
                    except Exception:
                        pass
                if not title:
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        title = parent.text.strip()
                    except Exception:
                        title = href

                if title and href != base + "/" and href != base:
                    # Also filter title after extraction (img alt, parent text)
                    title_lower = title.lower()
                    if any(s in title_lower for s in skip_texts):
                        continue
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

def _handle_chapter_preamble(driver):
    """Handle chapter preamble/intro pages that appear before questions.

    CKL (and potentially other sites) shows one or more instructional
    pages after launching a chapter, with a "Continue" or "Continue to
    Questions" button. These must be clicked through to reach actual
    quiz questions (which have radio buttons).
    """
    max_pages = 50  # Safety limit

    for page_num in range(max_pages):
        # If page has radio buttons, it's a question — stop
        if driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
            if page_num > 0:
                logger.info("  Clicked through %d preamble page(s)", page_num)
            return

        # Find a Continue button
        continue_btn = _find_continue_button(driver)
        if not continue_btn:
            return  # No continue button — might already be on a question page

        # Verify this looks like a preamble (not a results page with "Continue")
        if page_num == 0:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                has_preamble_indicator = (
                    bool(re.search(r'Page\s+\d+\s+of\s+\d+', body_text))
                    or "Back to Practice Set" in body_text
                    or "Instructions" in body_text
                    or bool(re.search(r'Step\s+\d+:', body_text))
                    or "Continue to Questions" in body_text
                )
                if not has_preamble_indicator:
                    return
            except Exception:
                return
            logger.info("  Detected chapter preamble pages, clicking through...")

        _safe_click(driver, continue_btn, "Continue")
        get_adaptive_delay().sleep("next_click")

    logger.warning("  Exceeded max preamble pages (%d)", max_pages)


def _find_continue_button(driver):
    """Find a Continue / Continue to Questions button on the page."""
    for text_match in ["Continue to Questions", "Continue"]:
        try:
            el = driver.find_element(By.PARTIAL_LINK_TEXT, text_match)
            if el.is_displayed():
                return el
        except NoSuchElementException:
            pass

    for text_match in ["Continue to Questions", "Continue"]:
        try:
            el = driver.find_element(
                By.XPATH, f"//*[contains(text(), '{text_match}')]"
            )
            if el.is_displayed() and el.tag_name in ("a", "button", "input"):
                return el
        except NoSuchElementException:
            pass

    for el in driver.find_elements(By.CSS_SELECTOR, "a, button, input[type='submit']"):
        try:
            text = (el.text or el.get_attribute("value") or "").strip().lower()
            if text.startswith("continue") and el.is_displayed():
                return el
        except StaleElementReferenceException:
            continue

    return None


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

    # Handle chapter preamble pages (e.g. "Continue to Questions" on CKL)
    _handle_chapter_preamble(driver)

    questions = []

    total = _get_total_questions(driver)
    logger.info("  %s question(s) to scrape", total or "Unknown number of")

    question_num = 0
    max_questions = total or 200
    consecutive_failures = 0

    while question_num < max_questions:
        # Check for graceful shutdown between questions
        if shutdown_requested():
            logger.info("  Shutdown requested — saving progress (%d questions scraped)", len(questions))
            from dataclasses import asdict
            save_chapter_checkpoint(
                chapter.launch_url,
                len(questions),
                [asdict(q) for q in questions],
            )
            break

        question_num += 1

        adaptive = get_adaptive_delay()

        try:
            q = _scrape_single_question(driver, question_num, total or 0)
            if q:
                questions.append(q)
                consecutive_failures = 0
                adaptive.on_success()
                logger.info(
                    "  [%d/%s] %s -> Answer: %s (delay: %.1fs)",
                    q.question_number,
                    total or "?",
                    q.question_text[:60] + ("..." if len(q.question_text) > 60 else ""),
                    q.correct_answer or "unknown",
                    adaptive.budget,
                )
                # Checkpoint every 5 questions for mid-chapter resume
                if len(questions) % 5 == 0:
                    from dataclasses import asdict
                    save_chapter_checkpoint(
                        chapter.launch_url,
                        len(questions),
                        [asdict(q) for q in questions],
                    )
            else:
                consecutive_failures += 1
                adaptive.on_failure()
                logger.warning("  Could not parse question %d", question_num)
                from scraper.browser import diagnose_page
                diagnose_page(driver, f"parse_fail_q{question_num}")

            # Too many consecutive failures -> something is wrong
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

            # Adaptive rate limiting between questions
            adaptive.sleep("rate_limit")

        except (TimeoutException, WebDriverException) as e:
            consecutive_failures += 1
            adaptive.on_failure()
            logger.warning("  Timeout/error on question %d (increasing delay): %s", question_num, e)
            if not _click_next_question(driver):
                break

        except Exception as e:
            consecutive_failures += 1
            adaptive.on_failure()
            logger.warning("  Error on question %d: %s", question_num, e)
            if not _click_next_question(driver):
                break

    chapter.questions = questions
    if not shutdown_requested():
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


def _get_body_text(driver):
    """Read body text once for caching. Returns empty string on failure."""
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception as e:
        logger.debug("Error reading body text: %s", e)
        return ""


def _scrape_single_question(driver, question_num, total):
    """Scrape one question: read it, submit an answer, read the feedback."""
    source_url = driver.current_url

    # Read body text ONCE for pre-submit extraction (eliminates 3 redundant reads)
    pre_body = _get_body_text(driver)

    # Detect question type
    question_type = _detect_question_type(pre_body)

    # Extract question text
    question_text = _extract_question_text(pre_body)
    if not question_text:
        return None

    # Extract answer choices (DOM-based first, then text fallback using cached body)
    choices = _extract_choices(driver, pre_body)

    # Submit answer to reveal correct answer + explanation
    _submit_answer(driver)
    get_adaptive_delay().sleep("feedback_wait")

    # Read body text ONCE for post-submit feedback extraction
    post_body = _get_body_text(driver)
    correct_answer, explanation = _extract_feedback(post_body)

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


def _detect_question_type(body_text):
    """Detect the question type from cached page text."""
    if "Multiple Choice" in body_text:
        return "Multiple Choice"
    if "True/False" in body_text or "True or False" in body_text:
        return "True/False"
    if "Fill in" in body_text:
        return "Fill in the Blank"
    if "Select all" in body_text or "select all" in body_text:
        return "Select All That Apply"
    return ""


_STOP_MARKERS = [
    "Back to Practice Set",
    "Next Question",
    "All Rights Reserved",
    "Check this box",
    "I'm still confused",
    "You will be able",
    "Submit",
]

_TYPE_LABELS = {
    "Multiple Choice", "True/False", "Fill in the Blank",
    "Select All That Apply", "Short Answer", "Essay",
}


def _extract_question_text(body_text):
    """Extract the question text between the header and answer choices from cached text."""
    try:
        text = body_text
        # Remove everything before the question marker
        marker = ">>>> Question <<<<"
        if marker in text:
            text = text.split(marker, 1)[1].strip()

        # Strip everything before "Question X of Y" if present
        q_of_match = re.search(r'Question\s+\d+\s+of\s+\d+', text)
        if q_of_match:
            text = text[q_of_match.end():].strip()

        lines = text.split("\n")
        question_lines = []
        for line in lines:
            stripped = line.strip()
            # Stop when we hit an answer choice
            if re.match(r'^[○●]?\s*[A-D]\.\s', stripped):
                break
            # Stop at nav/footer markers
            if any(m in stripped for m in _STOP_MARKERS):
                break
            # Stop at copyright line
            if re.match(r'^©\d{4}', stripped):
                break
            if not question_lines and not stripped:
                continue
            # Skip type labels
            if stripped in _TYPE_LABELS:
                continue
            # Skip "Question X of Y" if inline
            if re.match(r'^Question\s+\d+\s+of\s+\d+$', stripped):
                continue
            question_lines.append(stripped)

        question_text = " ".join(question_lines).strip()
        question_text = re.sub(r'\s+', ' ', question_text)
        return question_text

    except Exception as e:
        logger.debug("Error extracting question text: %s", e)
        return ""


def _extract_choices(driver, body_text=""):
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

    # Fallback: parse from cached page text (no extra DOM read)
    if not choices:
        choices = _extract_choices_from_text(body_text)

    if not choices:
        logger.warning("  No answer choices found on page")

    return choices


def _extract_choices_from_text(body_text):
    """Fallback: extract choices from cached page text using regex."""
    choices = []
    try:
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

        get_adaptive_delay().sleep("pre_submit")

        # Find Submit button
        submit_btn = _find_button(driver, ["submit"])
        if submit_btn:
            _safe_click(driver, submit_btn, "Submit button")
            get_adaptive_delay().sleep("post_submit")
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


def _extract_feedback(body_text):
    """Extract the correct answer and explanation from cached post-submit text."""
    correct_answer = ""
    explanation = ""

    try:
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
                get_adaptive_delay().sleep("next_click")
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
                get_adaptive_delay().sleep("next_click")
                return True
        except NoSuchElementException:
            pass

        # Broader search across buttons and links
        for el in driver.find_elements(By.CSS_SELECTOR, "a, button"):
            try:
                text = (el.text or el.get_attribute("value") or "").strip()
                if "next question" in text.lower() and el.is_displayed():
                    _safe_click(driver, el, "Next Question")
                    get_adaptive_delay().sleep("next_click")
                    return True
            except StaleElementReferenceException:
                continue

    except Exception as e:
        logger.debug("Error clicking Next Question: %s", e)

    return False
