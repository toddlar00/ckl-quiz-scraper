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
        """Handle CKL's chapter preamble/instruction pages.

        After launching a chapter, CKL may show one or more instructional
        pages before the actual quiz questions. These pages have:
          - Instructional text (no radio buttons / answer choices)
          - "Continue →" or "Continue to Questions" button
          - "Page X of Y" indicator
          - "Back to Practice Set" link

        This clicks through all preamble pages until reaching a question.
        """
        max_preamble_pages = 50  # Safety limit

        for page_num in range(max_preamble_pages):
            if not self._is_preamble_page():
                if page_num > 0:
                    logger.info("  Clicked through %d preamble page(s), now on questions", page_num)
                return

            if page_num == 0:
                logger.info("  Detected chapter preamble/instruction pages, clicking through...")

            continue_btn = self._find_continue_button()
            if continue_btn:
                _safe_click(self.driver, continue_btn, "Continue")
                get_adaptive_delay().sleep("next_click")
            else:
                logger.warning(
                    "  Preamble page detected but no Continue button found. URL: %s",
                    self.driver.current_url,
                )
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "preamble_no_continue")
                return

        logger.warning("  Exceeded max preamble pages (%d)", max_preamble_pages)

    def _is_preamble_page(self):
        """Check if the current page is a preamble/instruction page (not a question)."""
        try:
            # If there are radio buttons, it's a question page (MC/TF)
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if radios:
                return False

            body_text = self.driver.find_element(By.TAG_NAME, "body").text

            # If the page has a "Question X of Y" marker, it's a question page
            # (Short Answer / Fill-in / Essay won't have radio buttons)
            if re.search(r'Question\s+\d+\s+of\s+\d+', body_text):
                return False

            # If the page has a text input or textarea with a question type label,
            # it's an open-ended question, not preamble
            text_inputs = self.driver.find_elements(
                By.CSS_SELECTOR,
                "input[type='text']:not([name*='search']):not([name*='filter']), textarea"
            )
            if text_inputs and self._detect_type(body_text) in (
                "Short Answer", "Fill in the Blank", "Essay"
            ):
                return False

            # Check for preamble indicators
            has_continue = bool(self._find_continue_button())
            has_page_indicator = bool(re.search(r'Page\s+\d+\s+of\s+\d+', body_text))
            has_back_to_ps = "Back to Practice Set" in body_text
            has_instructions = "Instructions" in body_text
            has_step = bool(re.search(r'Step\s+\d+:', body_text))

            return has_continue and (has_page_indicator or has_back_to_ps or has_instructions or has_step)
        except Exception:
            return False

    def _find_continue_button(self):
        """Find a Continue / Continue to Questions button on the page."""
        # Try "Continue to Questions" first (more specific)
        for text_match in ["Continue to Questions", "Continue"]:
            try:
                el = self.driver.find_element(By.PARTIAL_LINK_TEXT, text_match)
                if el.is_displayed():
                    return el
            except NoSuchElementException:
                pass

        # XPath search
        for text_match in ["Continue to Questions", "Continue"]:
            try:
                el = self.driver.find_element(
                    By.XPATH, f"//*[contains(text(), '{text_match}')]"
                )
                if el.is_displayed() and el.tag_name in ("a", "button", "input"):
                    return el
            except NoSuchElementException:
                pass

        # Broad CSS search for any clickable element with "continue" text
        for el in self.driver.find_elements(By.CSS_SELECTOR, "a, button, input[type='submit']"):
            try:
                text = (el.text or el.get_attribute("value") or "").strip().lower()
                if text.startswith("continue") and el.is_displayed():
                    return el
            except StaleElementReferenceException:
                continue

        return None

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
            # CKL shows "Launch" for new chapters, "Revisit" for completed ones
            action_links = self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Launch")
            action_links += self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Revisit")
            if not action_links:
                logger.warning("No 'Launch' or 'Revisit' links found. URL: %s", self.driver.current_url)
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "no_launch_links")
                return chapters

            seen_hrefs = set()
            for link in action_links:
                try:
                    href = link.get_attribute("href") or ""
                    if not href or href in seen_hrefs:
                        continue
                    seen_hrefs.add(href)

                    link_text = link.text.strip().lower()
                    row = link.find_element(By.XPATH, "./ancestor::tr")
                    cells = row.find_elements(By.TAG_NAME, "td")

                    chapter_name = ""
                    status = ""
                    for cell in cells:
                        cell_text = cell.text.strip()
                        if cell_text.startswith("Chapter") or ":" in cell_text:
                            if len(cell_text) > 5 and cell_text not in ("Launch", "Revisit"):
                                chapter_name = cell_text
                        # Status can be: To Do, In Progress, Complete, Completed,
                        # or a score like "4/12", or "Revisiting"
                        if cell_text in ("To Do", "In Progress", "Complete", "Completed"):
                            status = cell_text
                        elif re.match(r'^\d+/\d+$', cell_text):
                            status = "Completed (%s)" % cell_text
                        elif cell_text.lower().startswith("revisiting"):
                            status = "Revisiting"
                    if not chapter_name:
                        chapter_name = row.text.strip()
                        for remove in ("Launch", "Revisit", "Revisiting"):
                            chapter_name = chapter_name.replace(remove, "")
                        chapter_name = chapter_name.strip()

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
            # Don't warn for question types that don't have choices
            qtype = self._detect_type(body_text)
            if qtype not in ("Short Answer", "Fill in the Blank", "Essay"):
                logger.warning("  No answer choices found on page")
        return choices

    def submit_answer(self):
        try:
            # MC / True-False: click a radio button
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            clicked_radio = False
            for radio in radios:
                if radio.is_displayed() and radio.is_enabled():
                    _safe_click(self.driver, radio, "radio button")
                    clicked_radio = True
                    break

            # Short Answer / Fill-in / Essay: type into the text editor.
            # CKL uses a rich-text editor (contenteditable div or iframe-based
            # like TinyMCE/CKEditor) with formatting toolbar (U, I, ¶, §, A).
            # Try multiple strategies to get text into the editor.
            if not clicked_radio:
                typed = self._type_into_editor("N/A")
                if not typed:
                    logger.warning("  Could not find text input or rich-text editor")

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

    def _type_into_editor(self, text):
        """Type text into whatever input is on the page (plain or rich-text).

        Tries in order:
          1. Plain <textarea> or <input type="text">
          2. contenteditable element (inline rich-text editor)
          3. iframe-based editor (TinyMCE, CKEditor)

        Returns True if text was entered successfully.
        """
        # Strategy 1: plain textarea / text input
        plain_inputs = self.driver.find_elements(
            By.CSS_SELECTOR,
            "textarea, input[type='text']:not([name*='search']):not([name*='filter'])"
        )
        for inp in plain_inputs:
            try:
                if inp.is_displayed() and inp.is_enabled():
                    inp.clear()
                    inp.send_keys(text)
                    logger.debug("  Typed into plain input/textarea")
                    return True
            except Exception:
                continue

        # Strategy 2: contenteditable div (common in modern rich-text editors)
        editable_els = self.driver.find_elements(
            By.CSS_SELECTOR, "[contenteditable='true']"
        )
        for el in editable_els:
            try:
                if el.is_displayed():
                    el.click()
                    el.send_keys(text)
                    logger.debug("  Typed into contenteditable element")
                    return True
            except Exception:
                continue

        # Strategy 3: iframe-based editor (TinyMCE, CKEditor, etc.)
        # These embed the editable area inside an iframe.
        iframes = self.driver.find_elements(By.CSS_SELECTOR, "iframe")
        for iframe in iframes:
            try:
                # Skip non-editor iframes (ads, tracking, etc.)
                iframe_id = (iframe.get_attribute("id") or "").lower()
                iframe_class = (iframe.get_attribute("class") or "").lower()
                iframe_title = (iframe.get_attribute("title") or "").lower()
                is_editor = any(
                    hint in f"{iframe_id} {iframe_class} {iframe_title}"
                    for hint in ("editor", "mce", "cke", "tinymce", "ckeditor",
                                 "rich", "text", "wysiwyg")
                )
                # Also check if iframe is near a formatting toolbar
                if not is_editor and not iframe.is_displayed():
                    continue

                self.driver.switch_to.frame(iframe)
                try:
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    if body.get_attribute("contenteditable") or body.is_enabled():
                        body.click()
                        body.send_keys(text)
                        logger.debug("  Typed into iframe-based editor")
                        return True
                except Exception:
                    pass
                finally:
                    self.driver.switch_to.default_content()
            except Exception:
                try:
                    self.driver.switch_to.default_content()
                except Exception:
                    pass
                continue

        # Strategy 4: JavaScript fallback — find any editable area and set its content
        try:
            typed = self.driver.execute_script("""
                // Try contenteditable
                var ed = document.querySelector('[contenteditable="true"]');
                if (ed) { ed.innerText = arguments[0]; return true; }
                // Try iframe editor body
                var iframes = document.querySelectorAll('iframe');
                for (var i = 0; i < iframes.length; i++) {
                    try {
                        var body = iframes[i].contentDocument.body;
                        if (body && body.contentEditable !== 'false') {
                            body.innerText = arguments[0];
                            return true;
                        }
                    } catch(e) {}
                }
                return false;
            """, text)
            if typed:
                logger.debug("  Typed into editor via JavaScript fallback")
                return True
        except Exception:
            pass

        return False

    def extract_feedback(self, body_text):
        correct_answer = ""
        explanation = ""

        # MC feedback: "The correct answer is C."
        match = re.search(r'The correct answer is\s+([A-D])', body_text, re.IGNORECASE)
        if match:
            correct_answer = match.group(1).upper()
        if not correct_answer:
            if re.search(r'\bCorrect[!.]', body_text) and "incorrect" not in body_text.lower():
                correct_answer = "A"

        # "Here's Why:" explanation (MC questions)
        heres_why = re.search(
            r"Here'?s\s+Why:?\s*(.+?)(?=Check this box|You will be able|I'm still confused|Next Question|Back to Practice|$)",
            body_text, re.DOTALL | re.IGNORECASE,
        )
        if heres_why:
            explanation = heres_why.group(1).strip()
            explanation = re.sub(r'\n\s*\n', '\n', explanation).strip()

        # Short Answer feedback: "Here is a sample answer:" followed by model text,
        # then a self-assessment prompt ("Did your answer include all of these components?")
        if not correct_answer and not explanation:
            sa_match = re.search(
                r'(?:Here\s+is\s+a\s+sample\s+answer|Sample\s+[Aa]nswer|Model\s+[Aa]nswer|Suggested\s+[Aa]nswer):?\s*(.+?)(?=Did your answer|Check this box|You will be able|I.m still confused|I got it|Select answer|\xa9\d{4}|$)',
                body_text, re.DOTALL | re.IGNORECASE,
            )
            if sa_match:
                explanation = sa_match.group(1).strip()
                explanation = re.sub(r'\n\s*\n', '\n', explanation).strip()
                correct_answer = "(sample answer)"

        # Handle the self-assessment radio buttons that appear after SA feedback.
        # CKL requires selecting one of: "I got it entirely right", "I got it
        # mostly right", etc. before you can click "Next Question".
        if "Did your answer include" in body_text or "I got it entirely right" in body_text:
            self._complete_self_assessment()

        if not correct_answer:
            logger.warning("  Could not determine correct answer from feedback")
        return correct_answer, explanation

    def _complete_self_assessment(self):
        """Click through the self-assessment radio buttons on SA feedback pages.

        After submitting a Short Answer, CKL shows a sample answer and asks
        the student to self-assess with radio buttons like:
          - I got it entirely right
          - I got it mostly right, but missed something
          - I got it about half right
          - I got a small part right
          - I didn't get anything right

        Select the last option (since we typed "N/A") so we can proceed.
        """
        try:
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if radios:
                # Select the last radio button ("I didn't get anything right")
                for radio in reversed(radios):
                    if radio.is_displayed() and radio.is_enabled():
                        _safe_click(self.driver, radio, "self-assessment radio")
                        logger.debug("  Clicked self-assessment radio for SA question")
                        break
        except Exception as e:
            logger.debug("  Could not click self-assessment radio: %s", e)

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

    # Lines/phrases that indicate we've passed the question text and
    # entered navigation, footer, or other page chrome.
    _STOP_MARKERS = [
        "Back to Practice Set",
        "Next Question",
        "All Rights Reserved",
        "Check this box",
        "I'm still confused",
        "You will be able",
        "Submit",
    ]

    # Type labels that appear on their own line before the question.
    _TYPE_LABELS = {
        "Multiple Choice", "True/False", "Fill in the Blank",
        "Select All That Apply", "Short Answer", "Essay",
    }

    @staticmethod
    def _detect_type(body_text):
        if "Multiple Choice" in body_text:
            return "Multiple Choice"
        if "True/False" in body_text or "True or False" in body_text:
            return "True/False"
        if "Short Answer" in body_text:
            return "Short Answer"
        if "Fill in" in body_text:
            return "Fill in the Blank"
        if "Select all" in body_text or "select all" in body_text:
            return "Select All That Apply"
        if "Essay" in body_text:
            return "Essay"
        return ""

    @classmethod
    def _extract_text(cls, body_text):
        try:
            text = body_text
            marker = ">>>> Question <<<<"
            if marker in text:
                text = text.split(marker, 1)[1].strip()

            # Strip everything before "Question X of Y" line if present,
            # so we start right at the question content.
            q_of_match = re.search(r'Question\s+\d+\s+of\s+\d+', text)
            if q_of_match:
                text = text[q_of_match.end():].strip()

            lines = text.split("\n")
            question_lines = []
            for line in lines:
                stripped = line.strip()
                # Stop at answer choices (MC)
                if re.match(r'^[○●]?\s*[A-D]\.\s', stripped):
                    break
                # Stop at nav/footer markers
                if any(m in stripped for m in cls._STOP_MARKERS):
                    break
                # Stop at copyright line
                if re.match(r'^©\d{4}', stripped):
                    break
                # Skip empty leading lines
                if not question_lines and not stripped:
                    continue
                # Skip type labels
                if stripped in cls._TYPE_LABELS:
                    continue
                # Skip "Question X of Y" if it somehow appears inline
                if re.match(r'^Question\s+\d+\s+of\s+\d+$', stripped):
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
