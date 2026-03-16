"""CKL (Core Knowledge for Lawyers) site scraper.

Implements the BaseScraper interface for coreknowledgeforlawyers.com.
"""

import logging
import re
import time

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.by import By

from scraper import config
from scraper.base import BaseScraper
from scraper.browser import login as browser_login
from scraper.quiz_scraper import (
    Chapter,
    _safe_click,
    _safe_get,
    _find_button,
    get_adaptive_delay,
)

logger = logging.getLogger(__name__)


class CKLScraper(BaseScraper):
    """Scraper for Core Knowledge for Lawyers quiz platform."""

    SITE_NAME = "Core Knowledge for Lawyers"
    BASE_URL = config.BASE_URL
    REQUIRES_LOGIN = True

    def login(self, username, password):
        return browser_login(self.driver)

    def navigate_to_home(self):
        """Handle CKL's post-login redirect to tutorial/welcome page.

        After login, CKL may redirect to the 'Welcome to CKL' tutorial
        (shows 'Page X of Y', 'Getting Started', or 'Accessing Practice Sets').
        This clicks HOME to get back to the practice sets grid.
        """
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            # Detect tutorial/welcome page indicators
            is_tutorial = (
                ("Getting Started" in body_text and "Page" in body_text)
                or "Accessing Practice Sets" in body_text
                or ("Welcome to CKL" in body_text and "Page" in body_text)
                or "Page 1 of" in body_text
                or "Page 2 of" in body_text
            )
            # Already on home page?
            is_home = "click the book image" in body_text.lower()

            if is_tutorial and not is_home:
                logger.info("Detected tutorial/welcome page, navigating to HOME...")
                try:
                    home_link = self.driver.find_element(By.LINK_TEXT, "HOME")
                    _safe_click(self.driver, home_link, "HOME link")
                    time.sleep(3)
                    logger.info("Navigated to home page. URL: %s", self.driver.current_url)
                except NoSuchElementException:
                    # Fallback: navigate directly to base URL
                    from scraper.quiz_scraper import _safe_get
                    _safe_get(self.driver, config.BASE_URL.rstrip("/"), "home page")
        except Exception as e:
            logger.debug("Home navigation check failed: %s", e)

    def prepare_chapter(self):
        """Handle CKL's chapter preamble page.

        After launching a chapter, CKL shows an intro page with:
          - Chapter title and description text
          - "Continue to Questions" button (must click to reach actual questions)
          - "Back to Practice Set" link

        This detects the preamble and clicks through to the questions.
        """
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text

            # Check if we're on a preamble page (has "Continue to Questions" button)
            if "Continue to Questions" not in body_text:
                return  # Already on a question page

            logger.info("  Detected chapter preamble page, clicking 'Continue to Questions'...")

            # Try finding the button/link by multiple strategies
            continue_btn = None

            # Strategy 1: Link text match
            try:
                continue_btn = self.driver.find_element(
                    By.PARTIAL_LINK_TEXT, "Continue to Questions"
                )
            except NoSuchElementException:
                pass

            # Strategy 2: XPath for any element containing the text
            if not continue_btn:
                try:
                    continue_btn = self.driver.find_element(
                        By.XPATH, "//*[contains(text(), 'Continue to Questions')]"
                    )
                except NoSuchElementException:
                    pass

            # Strategy 3: Button/link text search
            if not continue_btn:
                for el in self.driver.find_elements(By.CSS_SELECTOR, "a, button, input"):
                    try:
                        text = (el.text or el.get_attribute("value") or "").strip()
                        if "continue to questions" in text.lower():
                            if el.is_displayed():
                                continue_btn = el
                                break
                    except StaleElementReferenceException:
                        continue

            if continue_btn and continue_btn.is_displayed():
                _safe_click(self.driver, continue_btn, "Continue to Questions")
                get_adaptive_delay().sleep("next_click")
                logger.info("  Clicked 'Continue to Questions', now on question page")
            else:
                logger.warning(
                    "  'Continue to Questions' text found but button not clickable. "
                    "URL: %s", self.driver.current_url,
                )
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "continue_to_questions_not_found")

        except Exception as e:
            logger.debug("Chapter preamble handling: %s", e)

    def discover_practice_sets(self):
        base = config.BASE_URL.rstrip("/")
        _safe_get(self.driver, base, "home page")
        self.navigate_to_home()

        practice_sets = []
        try:
            links = self.driver.find_elements(By.TAG_NAME, "a")
            seen_urls = set()

            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    if not href or href == "#" or "javascript:" in href:
                        continue
                    if href in seen_urls or not href.startswith(base):
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
            diagnose_page(self.driver, "discover_practice_sets")

        # Deduplicate
        unique = []
        seen = set()
        for title, url in practice_sets:
            if url not in seen:
                seen.add(url)
                unique.append((title, url))

        if unique:
            logger.info("Discovered %d practice set(s):", len(unique))
            for i, (title, url) in enumerate(unique, 1):
                logger.info("  %d. %s", i, title)
        else:
            logger.warning("No practice sets found. Current URL: %s", self.driver.current_url)
            from scraper.browser import diagnose_page
            diagnose_page(self.driver, "no_practice_sets")

        return unique

    def discover_chapters(self, practice_set_url):
        _safe_get(self.driver, practice_set_url, "practice set")
        chapters = []

        try:
            launch_links = self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Launch")
            if not launch_links:
                logger.warning("No 'Launch' links found. URL: %s", self.driver.current_url)
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "no_launch_links")
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
                        chapter_name = row.text.strip().replace("Launch", "").strip()

                    chapters.append(Chapter(
                        chapter_name=chapter_name, launch_url=href, status=status,
                    ))
                except (StaleElementReferenceException, NoSuchElementException):
                    continue

        except Exception as e:
            logger.error("Error discovering chapters: %s", e)

        logger.info("Found %d chapter(s):", len(chapters))
        for ch in chapters:
            logger.info("  - %s [%s]", ch.chapter_name, ch.status)
        return chapters

    def get_total_questions(self, body_text):
        match = re.search(r'Question\s+\d+\s+of\s+(\d+)', body_text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d+)\s+of\s+(\d+)', body_text)
        if match:
            return int(match.group(2))
        return None

    def extract_question(self, body_text):
        question_type = self._detect_type(body_text)
        question_text = self._extract_text(body_text)
        return question_type, question_text

    def extract_choices(self, body_text):
        """Extract choices from radio buttons (DOM), fallback to text regex."""
        choices = []
        try:
            radio_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            for radio in radio_inputs:
                try:
                    radio_id = radio.get_attribute("id")
                    label = None
                    if radio_id:
                        labels = self.driver.find_elements(
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
                        letter, text = match.group(1), match.group(2).strip()
                    else:
                        letter, text = chr(65 + len(choices)), label_text
                    choices.append({"label": letter, "text": text, "is_correct": False})
                except (StaleElementReferenceException, NoSuchElementException):
                    continue
        except Exception as e:
            logger.debug("Error extracting choices from radio buttons: %s", e)

        if not choices:
            choices = self._extract_choices_from_text(body_text)
        if not choices:
            logger.warning("  No answer choices found on page")
        return choices

    def submit_answer(self):
        try:
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            for radio in radios:
                if radio.is_displayed() and radio.is_enabled():
                    _safe_click(self.driver, radio, "radio button")
                    break
            get_adaptive_delay().sleep("pre_submit")
            submit_btn = _find_button(self.driver, ["submit"])
            if submit_btn:
                _safe_click(self.driver, submit_btn, "Submit button")
                get_adaptive_delay().sleep("post_submit")
            else:
                logger.warning("  Could not find Submit button")
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "no_submit_button")
        except Exception as e:
            logger.warning("  Error submitting answer: %s", e)

    def extract_feedback(self, body_text):
        correct_answer = ""
        explanation = ""

        match = re.search(r'The correct answer is\s+([A-D])', body_text, re.IGNORECASE)
        if match:
            correct_answer = match.group(1).upper()
        if not correct_answer:
            if re.search(r'\bCorrect[!.]', body_text) and "incorrect" not in body_text.lower():
                correct_answer = "A"

        heres_why = re.search(
            r"Here'?s\s+Why:?\s*(.+?)(?=Check this box|You will be able|I'm still confused|Next Question|Back to Practice|$)",
            body_text, re.DOTALL | re.IGNORECASE,
        )
        if heres_why:
            explanation = heres_why.group(1).strip()
            explanation = re.sub(r'\n\s*\n', '\n', explanation).strip()

        if not correct_answer:
            logger.warning("  Could not determine correct answer from feedback")
        return correct_answer, explanation

    def extract_choice_explanations(self, body_text, choices, correct_answer):
        """Extract per-choice explanations from CKL feedback page.

        CKL feedback may include:
          - "A. <choice text> — Correct/Incorrect. <reason>"
          - Lettered explanations like "A) <reason>"
          - General explanation applied to correct answer, with generic
            "Incorrect" note for wrong answers.
        """
        explanations = {}

        # Pattern 1: Labeled per-choice feedback "A. ... Correct/Incorrect ..."
        per_choice = re.findall(
            r'([A-D])\.\s+.+?(?:Correct|Incorrect)[.!]?\s*(.*?)(?=[A-D]\.\s|Check this box|Next Question|Back to Practice|$)',
            body_text, re.DOTALL | re.IGNORECASE,
        )
        if per_choice:
            for label, reason in per_choice:
                reason = re.sub(r'\s+', ' ', reason).strip()
                if reason:
                    explanations[label.upper()] = reason

        # Pattern 2: Feedback blocks keyed by letter "A) reason" or "A: reason"
        if not explanations:
            per_choice2 = re.findall(
                r'([A-D])[):]\s+(.+?)(?=[A-D][):]|\Z)',
                body_text, re.DOTALL,
            )
            # Only use if these look like feedback (post-submit), not choices
            if per_choice2 and correct_answer:
                for label, reason in per_choice2:
                    reason = re.sub(r'\s+', ' ', reason).strip()
                    if len(reason) > 10:  # Skip very short fragments
                        explanations[label.upper()] = reason

        # Pattern 3: DOM-based — look for per-choice feedback elements
        if not explanations:
            try:
                feedback_els = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    ".feedback, .answer-feedback, .choice-feedback, "
                    "[class*='feedback'], [class*='explanation']"
                )
                for el in feedback_els:
                    text = el.text.strip()
                    if not text:
                        continue
                    match = re.match(r'^([A-D])[.):\s]+(.+)', text, re.DOTALL)
                    if match:
                        label = match.group(1).upper()
                        reason = re.sub(r'\s+', ' ', match.group(2)).strip()
                        if reason:
                            explanations[label] = reason
            except Exception:
                pass

        # Fallback: apply general explanation to correct answer, generic note to others
        if not explanations and correct_answer:
            general = ""
            heres_why = re.search(
                r"Here'?s\s+Why:?\s*(.+?)(?=Check this box|You will be able|I'm still confused|Next Question|Back to Practice|$)",
                body_text, re.DOTALL | re.IGNORECASE,
            )
            if heres_why:
                general = re.sub(r'\s+', ' ', heres_why.group(1)).strip()

            for choice in choices:
                label = choice["label"]
                if label == correct_answer:
                    explanations[label] = f"Correct. {general}" if general else "Correct."
                else:
                    explanations[label] = f"Incorrect. The correct answer is {correct_answer}." + (f" {general}" if general else "")

        return explanations

    def click_next_question(self):
        try:
            try:
                next_link = self.driver.find_element(By.PARTIAL_LINK_TEXT, "Next Question")
                if next_link.is_displayed():
                    _safe_click(self.driver, next_link, "Next Question")
                    get_adaptive_delay().sleep("next_click")
                    return True
            except NoSuchElementException:
                pass
            try:
                next_el = self.driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Next Question')]"
                )
                if next_el.is_displayed():
                    _safe_click(self.driver, next_el, "Next Question")
                    get_adaptive_delay().sleep("next_click")
                    return True
            except NoSuchElementException:
                pass
            for el in self.driver.find_elements(By.CSS_SELECTOR, "a, button"):
                try:
                    text = (el.text or el.get_attribute("value") or "").strip()
                    if "next question" in text.lower() and el.is_displayed():
                        _safe_click(self.driver, el, "Next Question")
                        get_adaptive_delay().sleep("next_click")
                        return True
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            logger.debug("Error clicking Next Question: %s", e)
        return False

    # ------------------------------------------------------------------
    # CKL-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_type(body_text):
        if "Multiple Choice" in body_text:
            return "Multiple Choice"
        if "True/False" in body_text or "True or False" in body_text:
            return "True/False"
        if "Fill in" in body_text:
            return "Fill in the Blank"
        if "Select all" in body_text or "select all" in body_text:
            return "Select All That Apply"
        return ""

    @staticmethod
    def _extract_text(body_text):
        try:
            text = body_text
            marker = ">>>> Question <<<<"
            if marker in text:
                text = text.split(marker, 1)[1].strip()
            lines = text.split("\n")
            question_lines = []
            for line in lines:
                stripped = line.strip()
                if re.match(r'^[○●]?\s*[A-D]\.\s', stripped):
                    break
                if not question_lines and not stripped:
                    continue
                if stripped in ("Multiple Choice", "True/False",
                                "Fill in the Blank", "Select All That Apply"):
                    continue
                question_lines.append(stripped)
            result = " ".join(question_lines).strip()
            return re.sub(r'\s+', ' ', result)
        except Exception as e:
            logger.debug("Error extracting question text: %s", e)
            return ""

    @staticmethod
    def _extract_choices_from_text(body_text):
        choices = []
        try:
            pattern = re.compile(
                r'([A-D])\.\s+(.+?)(?=\n\s*[A-D]\.\s|\nSubmit|\Z)', re.DOTALL
            )
            for label, text in pattern.findall(body_text):
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
