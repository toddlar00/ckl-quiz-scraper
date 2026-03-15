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

import logging
import re
import time
from dataclasses import dataclass, field

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper import config

logger = logging.getLogger(__name__)


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


def discover_practice_sets(driver):
    """Find all Practice Sets on the home page after login.

    The home page shows a grid of book covers. Each is clickable and
    leads to a Practice Set page with chapters.
    Returns list of (title, url) tuples.
    """
    base = config.BASE_URL.rstrip("/")
    driver.get(base)
    time.sleep(3)

    practice_sets = []

    # The homepage shows book cards/tiles - each has a title and a clickable image/link
    # Look for links that contain book images or practice set titles
    try:
        # Try finding clickable book containers
        # Based on the screenshot, each practice set is in a card with:
        # - A book cover image (clickable)
        # - A title below it
        # - Status badge ("IN PROGRESS", "NEW!")
        # - "Join a Class" link

        # Strategy: find all links that contain images (book covers)
        links = driver.find_elements(By.TAG_NAME, "a")
        seen_urls = set()

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                if not href or href == "#" or "javascript:" in href:
                    continue
                if href in seen_urls:
                    continue

                # Skip non-internal links
                if not href.startswith(base):
                    continue

                # Skip utility links
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

                # Get title from link text or nearby elements
                title = link.text.strip()
                if not title:
                    # Try getting title from parent container
                    try:
                        parent = link.find_element(By.XPATH, "./..")
                        title = parent.text.strip()
                    except Exception:
                        title = href

                # Filter to likely practice set links (not homepage anchors)
                if title and href != base + "/" and href != base:
                    seen_urls.add(href)
                    practice_sets.append((title, href))

            except StaleElementReferenceException:
                continue

    except Exception as e:
        logger.error("Error discovering practice sets: %s", e)

    # Deduplicate by URL, keeping first occurrence
    unique = []
    seen = set()
    for title, url in practice_sets:
        if url not in seen:
            seen.add(url)
            unique.append((title, url))

    logger.info("Discovered %d practice set(s)", len(unique))
    for title, url in unique:
        logger.info("  - %s", title)

    return unique


def discover_chapters(driver, practice_set_url):
    """Navigate to a Practice Set and find all chapter "Launch" links.

    The Practice Set page has a table under "A. Practice Questions" with:
    - Checkbox column
    - "Launch" link
    - Chapter name (e.g. "Chapter 2: Subject Matter Jurisdiction")
    - Complete Date / MDT columns
    - Status ("In Progress", "To Do")

    Returns list of Chapter objects.
    """
    driver.get(practice_set_url)
    time.sleep(3)

    chapters = []

    try:
        # Find all "Launch" links on the page
        launch_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Launch")

        for launch_link in launch_links:
            try:
                href = launch_link.get_attribute("href") or ""
                if not href:
                    continue

                # Get the chapter name from the same row
                row = launch_link.find_element(By.XPATH, "./ancestor::tr")
                cells = row.find_elements(By.TAG_NAME, "td")

                chapter_name = ""
                status = ""

                for cell in cells:
                    cell_text = cell.text.strip()
                    # The chapter name cell contains text like "Chapter 2: ..."
                    if cell_text.startswith("Chapter") or ":" in cell_text:
                        if len(cell_text) > 5 and cell_text != "Launch":
                            chapter_name = cell_text
                    # Status cell
                    if cell_text in ("To Do", "In Progress", "Complete", "Completed"):
                        status = cell_text

                if not chapter_name:
                    # Fallback: get all text from the row
                    row_text = row.text.strip()
                    # Remove "Launch" and status from the text
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

    logger.info("Found %d chapter(s) in practice set", len(chapters))
    for ch in chapters:
        logger.info("  - %s [%s]", ch.chapter_name, ch.status)

    return chapters


def scrape_chapter_questions(driver, chapter):
    """Scrape all questions from a chapter by launching it and iterating.

    CKL quiz flow:
    1. Click "Launch" → lands on Question 1 of N
    2. Page shows: question type, question text, radio choices A-D
    3. Select an answer, click "Submit"
    4. Page reveals: "The correct answer is X" + "Here's Why:" explanation
    5. Click "Next Question" to advance
    6. Repeat until all N questions are done

    To get the correct answer and explanation, we must submit an answer
    for each question. We select option A by default (the answer doesn't
    matter since we read the correct answer from the feedback).
    """
    driver.get(chapter.launch_url)
    time.sleep(3)

    questions = []

    # Determine total questions from "Question X of Y" indicator
    total = _get_total_questions(driver)
    logger.info("Chapter has %s question(s)", total or "unknown")

    question_num = 0
    max_questions = 200  # safety limit

    while question_num < max_questions:
        question_num += 1

        try:
            q = _scrape_single_question(driver, question_num, total or 0)
            if q:
                questions.append(q)
                logger.debug(
                    "  Q%d: %s... -> %s",
                    q.question_number,
                    q.question_text[:60],
                    q.correct_answer,
                )
            else:
                logger.warning("  Could not parse question %d", question_num)

            # Try to go to next question
            if not _click_next_question(driver):
                logger.info("  No more questions (scraped %d)", len(questions))
                break

        except Exception as e:
            logger.warning("  Error on question %d: %s", question_num, e)
            # Try to recover by clicking Next
            if not _click_next_question(driver):
                break

    chapter.questions = questions
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

    # Also try looking at page source for "of N" pattern
    try:
        page = driver.page_source
        match = re.search(r'(\d+)\s+of\s+(\d+)', page)
        if match:
            return int(match.group(2))
    except Exception:
        pass

    return None


def _scrape_single_question(driver, question_num, total):
    """Scrape one question: read it, submit an answer, read the feedback.

    Returns a QuizQuestion with the correct answer and explanation.
    """
    wait = WebDriverWait(driver, 10)
    source_url = driver.current_url

    # --- Read the question ---

    # Get question type (e.g. "Multiple Choice")
    question_type = ""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "Multiple Choice" in body_text:
            question_type = "Multiple Choice"
        elif "True/False" in body_text or "True or False" in body_text:
            question_type = "True/False"
        elif "Fill in" in body_text:
            question_type = "Fill in the Blank"
    except Exception:
        pass

    # Get question text — it's the paragraph(s) between the question header
    # and the answer choices
    question_text = _extract_question_text(driver)

    if not question_text:
        return None

    # --- Read the answer choices ---
    choices = _extract_choices(driver)

    # --- Submit an answer to reveal correct answer + explanation ---
    _submit_answer(driver)
    time.sleep(2)

    # --- Read the feedback ---
    correct_answer, explanation = _extract_feedback(driver)

    # Update which choice is correct based on the feedback
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


def _extract_question_text(driver):
    """Extract the question text from the current page.

    The question text appears after ">>>> Question <<<<" header and before
    the radio button choices.
    """
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Remove everything before the question marker
        marker = ">>>> Question <<<<"
        if marker in body_text:
            body_text = body_text.split(marker, 1)[1].strip()

        # Remove everything starting from the first choice label
        # Choices start with a line containing just "A." or "○ A." pattern
        lines = body_text.split("\n")
        question_lines = []
        for line in lines:
            stripped = line.strip()
            # Stop when we hit an answer choice line
            if re.match(r'^[○●]?\s*[A-D]\.\s', stripped):
                break
            # Skip empty lines at start
            if not question_lines and not stripped:
                continue
            # Skip the question type label
            if stripped in ("Multiple Choice", "True/False", "Fill in the Blank"):
                continue
            question_lines.append(stripped)

        question_text = " ".join(question_lines).strip()

        # Clean up multiple spaces
        question_text = re.sub(r'\s+', ' ', question_text)

        return question_text

    except Exception as e:
        logger.debug("Error extracting question text: %s", e)
        return ""


def _extract_choices(driver):
    """Extract answer choices (A, B, C, D) from radio buttons on the page."""
    choices = []

    try:
        # Find radio button labels — CKL uses radio inputs with labels
        # The labels show "A. <text>", "B. <text>", etc.
        radio_inputs = driver.find_elements(
            By.CSS_SELECTOR, "input[type='radio']"
        )

        for radio in radio_inputs:
            try:
                # Get the label associated with this radio
                radio_id = radio.get_attribute("id")
                label = None

                if radio_id:
                    labels = driver.find_elements(
                        By.CSS_SELECTOR, f"label[for='{radio_id}']"
                    )
                    if labels:
                        label = labels[0]

                if not label:
                    # Try finding label as parent or sibling
                    try:
                        label = radio.find_element(By.XPATH, "./ancestor::label")
                    except NoSuchElementException:
                        try:
                            label = radio.find_element(By.XPATH, "./following-sibling::label")
                        except NoSuchElementException:
                            pass

                if label:
                    label_text = label.text.strip()
                else:
                    # Get text from parent container
                    parent = radio.find_element(By.XPATH, "./..")
                    label_text = parent.text.strip()

                if not label_text:
                    continue

                # Parse "A. Some answer text" or just get the letter
                match = re.match(r'^([A-D])\.\s*(.*)', label_text, re.DOTALL)
                if match:
                    letter = match.group(1)
                    text = match.group(2).strip()
                else:
                    # Assign letter based on order
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
        logger.debug("Error extracting choices: %s", e)

    # Fallback: parse from body text if no radio buttons found
    if not choices:
        choices = _extract_choices_from_text(driver)

    return choices


def _extract_choices_from_text(driver):
    """Fallback: extract choices from page text using regex."""
    choices = []
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        pattern = re.compile(r'([A-D])\.\s+(.+?)(?=\n\s*[A-D]\.\s|\nSubmit|\Z)', re.DOTALL)
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
    """Select the first available radio button and click Submit.

    We need to submit an answer to reveal the correct answer and explanation.
    The choice we select doesn't matter — we read the correct answer from feedback.
    """
    try:
        # Select the first radio button (option A)
        radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        if radios:
            # Click the first radio that's visible and enabled
            for radio in radios:
                if radio.is_displayed() and radio.is_enabled():
                    try:
                        radio.click()
                    except Exception:
                        # Try JavaScript click as fallback
                        driver.execute_script("arguments[0].click();", radio)
                    break

        time.sleep(1)

        # Click the "Submit" button
        submit_btn = None

        # Try by button text
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if btn.text.strip().lower() == "submit" and btn.is_displayed():
                submit_btn = btn
                break

        if not submit_btn:
            # Try input[type='submit']
            submits = driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
            for btn in submits:
                if btn.is_displayed():
                    submit_btn = btn
                    break

        if not submit_btn:
            # Try by value attribute
            submits = driver.find_elements(By.CSS_SELECTOR, "input[value='Submit'], button[value='Submit']")
            for btn in submits:
                if btn.is_displayed():
                    submit_btn = btn
                    break

        if submit_btn:
            submit_btn.click()
            time.sleep(2)
        else:
            logger.warning("Could not find Submit button")

    except Exception as e:
        logger.warning("Error submitting answer: %s", e)


def _extract_feedback(driver):
    """Extract the correct answer letter and explanation from feedback.

    After submitting, the page shows feedback like:
        "Sorry! You are incorrect."
        "The correct answer is C."
        "Here's Why:"
        "<explanation text>"

    Or for correct answers:
        "Correct!"
        "Here's Why:"
        "<explanation text>"
    """
    correct_answer = ""
    explanation = ""

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Extract correct answer letter: "The correct answer is C."
        match = re.search(
            r'The correct answer is\s+([A-D])',
            body_text,
            re.IGNORECASE,
        )
        if match:
            correct_answer = match.group(1).upper()

        # If user got it right, the feedback might not say "correct answer is"
        # Look for "Correct!" without "incorrect"
        if not correct_answer:
            if re.search(r'\bCorrect[!.]', body_text) and "incorrect" not in body_text.lower():
                # The selected answer was correct — we selected A
                correct_answer = "A"

        # Extract explanation: everything after "Here's Why:"
        heres_why_match = re.search(
            r"Here'?s\s+Why:?\s*(.+?)(?=Check this box|You will be able|I'm still confused|Next Question|Back to Practice|$)",
            body_text,
            re.DOTALL | re.IGNORECASE,
        )
        if heres_why_match:
            explanation = heres_why_match.group(1).strip()
            # Clean up whitespace
            explanation = re.sub(r'\n\s*\n', '\n', explanation)
            explanation = explanation.strip()

    except Exception as e:
        logger.debug("Error extracting feedback: %s", e)

    return correct_answer, explanation


def _click_next_question(driver):
    """Click the 'Next Question' button to advance to the next question.

    Returns True if successfully navigated, False if no button found
    (meaning we've reached the end).
    """
    try:
        # Look for "Next Question" link/button — in the screenshot it's
        # a button/link at the bottom right
        next_selectors = [
            "a",
            "button",
            "input[type='button']",
            "input[type='submit']",
        ]

        for selector in next_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                try:
                    text = (el.text or el.get_attribute("value") or "").strip()
                    if "next question" in text.lower() and el.is_displayed():
                        el.click()
                        time.sleep(3)
                        return True
                except StaleElementReferenceException:
                    continue

        # Try finding by partial link text
        try:
            next_link = driver.find_element(By.PARTIAL_LINK_TEXT, "Next Question")
            if next_link.is_displayed():
                next_link.click()
                time.sleep(3)
                return True
        except NoSuchElementException:
            pass

        # Try XPath for any element containing "Next Question"
        try:
            next_el = driver.find_element(
                By.XPATH, "//*[contains(text(), 'Next Question')]"
            )
            if next_el.is_displayed():
                next_el.click()
                time.sleep(3)
                return True
        except NoSuchElementException:
            pass

    except Exception as e:
        logger.debug("Error clicking Next Question: %s", e)

    return False
