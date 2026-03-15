"""West Academic site scraper.

Supports login via:
  - Email/password (direct West Academic account)
  - Google OAuth (Sign in with Google)

Compatible domains:
  - westacademic.com (main site)
  - subscription.westacademic.com (Study Aids Collection — quizzes, outlines)
  - eproducts.westacademic.com (eProducts — eBooks, quiz banks)

Authentication flows through signin.westacademic.com, which serves all three domains.
"""

import logging
import re
import time

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper.base import BaseScraper
from scraper.google_auth import find_google_login_button, google_login, google_login_via_button
from scraper.quiz_scraper import (
    Chapter,
    _safe_click,
    _safe_get,
    get_adaptive_delay,
)

logger = logging.getLogger(__name__)

# West Academic domain mapping
WA_DOMAINS = {
    "signin": "https://signin.westacademic.com",
    "subscription": "https://subscription.westacademic.com",
    "eproducts": "https://eproducts.westacademic.com",
    "main": "https://www.westacademic.com",
}

WA_LOGIN_URL = "https://signin.westacademic.com/Security/Login"
WA_SSO_URL = "https://eproducts.westacademic.com/Security/SingleSignOn"


class WestAcademicScraper(BaseScraper):
    """Scraper for West Academic quiz platform.

    West Academic Study Aids Collection provides interactive multiple-choice
    practice questions (Exam Pro) across many legal subjects. Quizzes can be
    keyed to specific casebooks.
    """

    SITE_NAME = "West Academic"
    BASE_URL = "https://subscription.westacademic.com"
    REQUIRES_LOGIN = True

    # Login method: "form" (email/password) or "google" (Google OAuth)
    LOGIN_METHOD = "form"

    def login(self, username, password):
        """Log into West Academic.

        Supports two login methods:
          - "form": Direct email/password via signin.westacademic.com
          - "google": Google OAuth flow

        The login method is determined by the WA_LOGIN_METHOD env var
        or by auto-detection (if a Google button is found on the page).

        Args:
            username: Email (West Academic account or Google email).
            password: Password for the account.

        Returns:
            True on success, False on failure.
        """
        import os
        login_method = os.getenv("WA_LOGIN_METHOD", "form").lower()

        # Try cookie-based fast login first
        if self._try_cookie_login():
            return True

        if login_method == "google":
            success = self._login_google(username, password)
        else:
            success = self._login_form(username, password)

        if success:
            self._save_cookies()
            # Verify we can access the quiz content
            _safe_get(self.driver, self.BASE_URL, "West Academic home")
            if self._is_logged_in():
                logger.info("Login verified — access to Study Aids confirmed")
                return True
            else:
                logger.warning("Login succeeded but Study Aids access not confirmed")
                return True  # May still work with cross-domain cookies

        return False

    def _login_form(self, username, password):
        """Login via email/password form at signin.westacademic.com."""
        logger.info("Attempting West Academic form login...")
        _safe_get(self.driver, WA_LOGIN_URL, "WA login page")

        wait = WebDriverWait(self.driver, 15)

        try:
            # Wait for the JS-rendered login form to appear
            email_field = self._find_email_field(wait)
            if not email_field:
                # Try SSO endpoint as fallback
                logger.info("No login form at primary URL, trying SSO endpoint...")
                _safe_get(self.driver, WA_SSO_URL, "WA SSO page")
                email_field = self._find_email_field(wait)

            if not email_field:
                logger.error("Could not find email field on West Academic login page")
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "wa_no_email_field")
                return False

            password_field = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']"))
            )

            email_field.clear()
            email_field.send_keys(username)
            time.sleep(0.3)
            password_field.clear()
            password_field.send_keys(password)
            time.sleep(0.3)

            # Find and click submit
            submit_btn = self._find_submit_button()
            if submit_btn:
                submit_btn.click()
            else:
                form = password_field.find_element(By.XPATH, "./ancestor::form")
                form.submit()

            time.sleep(4)

            # Check for errors
            body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            error_indicators = [
                "invalid", "incorrect", "failed", "error",
                "wrong password", "unable to log in", "not found",
            ]
            for indicator in error_indicators:
                if indicator in body_text:
                    logger.error("Login failed: '%s' found on page", indicator)
                    return False

            logger.info("Form login completed. URL: %s", self.driver.current_url)
            return True

        except TimeoutException:
            logger.error("Login form did not load within timeout")
            from scraper.browser import diagnose_page
            diagnose_page(self.driver, "wa_login_timeout")
            return False
        except Exception as e:
            logger.error("Form login failed: %s", e)
            return False

    def _login_google(self, email, password):
        """Login via Google OAuth button on West Academic sign-in page."""
        logger.info("Attempting West Academic Google login...")

        # Navigate to the login page where Google button should appear
        _safe_get(self.driver, WA_LOGIN_URL, "WA login page")
        time.sleep(3)  # Wait for JS to render

        # Also check the SSO endpoint
        if not find_google_login_button(self.driver):
            logger.info("No Google button at login page, trying SSO endpoint...")
            _safe_get(self.driver, WA_SSO_URL, "WA SSO page")
            time.sleep(3)

        success = google_login_via_button(self.driver, email, password)

        if success:
            # Wait for redirect back to West Academic
            time.sleep(5)
            logger.info("Google login completed. URL: %s", self.driver.current_url)

        return success

    def _try_cookie_login(self):
        """Attempt login using previously saved cookies."""
        import json
        import os

        cookie_file = ".wa_cookies.json"
        if not os.path.exists(cookie_file):
            return False

        try:
            logger.info("Attempting login via saved cookies...")
            with open(cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            # Navigate to each domain to set cookies
            for domain_url in [WA_DOMAINS["subscription"], WA_DOMAINS["signin"]]:
                try:
                    self.driver.get(domain_url)
                    time.sleep(2)
                    for cookie in cookies:
                        cookie_domain = cookie.get("domain", "")
                        # Only add cookies matching the current domain
                        if cookie_domain in domain_url or domain_url.endswith(cookie_domain):
                            c = dict(cookie)
                            c.pop("sameSite", None)
                            c.pop("expiry", None)
                            try:
                                self.driver.add_cookie(c)
                            except Exception:
                                continue
                except Exception:
                    continue

            # Verify access
            self.driver.get(self.BASE_URL)
            time.sleep(3)
            if self._is_logged_in():
                logger.info("Cookie login successful!")
                return True

            logger.info("Cookie login failed, falling back to form login")
        except Exception as e:
            logger.debug("Cookie login error: %s", e)

        return False

    def _save_cookies(self):
        """Save cookies for session reuse."""
        import json
        try:
            cookies = self.driver.get_cookies()
            with open(".wa_cookies.json", "w", encoding="utf-8") as f:
                json.dump(cookies, f)
            logger.debug("Saved %d cookies", len(cookies))
        except Exception as e:
            logger.debug("Could not save cookies: %s", e)

    def _is_logged_in(self):
        """Check if we appear to be logged in to West Academic."""
        try:
            body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            logged_in_indicators = [
                "my bookshelf", "sign out", "log out", "my account",
                "study aids", "bookshelf", "welcome",
            ]
            login_page_indicators = [
                "sign in", "log in", "create account", "forgot password",
            ]
            has_logged_in = any(ind in body for ind in logged_in_indicators)
            has_login_page = any(ind in body for ind in login_page_indicators)
            return has_logged_in and not has_login_page
        except Exception:
            return False

    def _find_email_field(self, wait):
        """Find the email input field on the login page."""
        selectors = [
            "input[type='email']",
            "input[name='Email']",
            "input[name='email']",
            "input[name='UserName']",
            "input[name='username']",
            "input[id='Email']",
            "input[id='UserName']",
            "input[type='text']",
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

    def _find_submit_button(self):
        """Find the login submit button."""
        for selector in ["input[type='submit']", "button[type='submit']"]:
            btns = self.driver.find_elements(By.CSS_SELECTOR, selector)
            for btn in btns:
                if btn.is_displayed():
                    return btn

        for el in self.driver.find_elements(By.CSS_SELECTOR, "button, a.btn, input[type='button']"):
            try:
                text = (el.text or el.get_attribute("value") or "").strip().lower()
                if text in ("sign in", "log in", "login", "submit"):
                    if el.is_displayed():
                        return el
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_practice_sets(self):
        """Find all quiz collections on the Study Aids bookshelf.

        West Academic organizes quizzes by subject/casebook on the bookshelf.
        """
        _safe_get(self.driver, self.BASE_URL, "Study Aids home")
        time.sleep(2)

        practice_sets = []
        try:
            # West Academic Study Aids uses a bookshelf grid
            # Look for quiz links, book cards, or subject categories
            selectors = [
                "a[href*='Quiz']",
                "a[href*='quiz']",
                "a[href*='Book']",
                "a[href*='book']",
                ".book-card a",
                ".bookshelf-item a",
                ".quiz-item a",
            ]
            seen_urls = set()

            for selector in selectors:
                links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for link in links:
                    try:
                        href = link.get_attribute("href") or ""
                        if not href or href == "#" or href in seen_urls:
                            continue
                        if "javascript:" in href:
                            continue
                        title = link.text.strip()
                        if not title:
                            try:
                                img = link.find_element(By.TAG_NAME, "img")
                                title = (img.get_attribute("alt") or "").strip()
                            except NoSuchElementException:
                                pass
                        if not title:
                            title = href.split("/")[-1]
                        seen_urls.add(href)
                        practice_sets.append((title, href))
                    except StaleElementReferenceException:
                        continue

            # Fallback: scan all links for quiz-related content
            if not practice_sets:
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                for link in all_links:
                    try:
                        href = link.get_attribute("href") or ""
                        text = link.text.strip()
                        if not href or not text or href in seen_urls:
                            continue
                        # Filter for quiz/study-related links
                        combined = f"{text} {href}".lower()
                        if any(kw in combined for kw in [
                            "quiz", "exam", "practice", "question", "assessment",
                            "study aid", "bookshelf",
                        ]):
                            skip_texts = [
                                "sign", "log", "help", "support", "contact",
                                "privacy", "terms", "cookie", "cart",
                            ]
                            if any(s in text.lower() for s in skip_texts):
                                continue
                            seen_urls.add(href)
                            practice_sets.append((text, href))
                    except StaleElementReferenceException:
                        continue

        except Exception as e:
            logger.error("Error discovering practice sets: %s", e)
            from scraper.browser import diagnose_page
            diagnose_page(self.driver, "wa_discover_practice_sets")

        if practice_sets:
            logger.info("Discovered %d practice set(s):", len(practice_sets))
            for i, (title, _) in enumerate(practice_sets, 1):
                logger.info("  %d. %s", i, title)
        else:
            logger.warning("No practice sets found. URL: %s", self.driver.current_url)
            from scraper.browser import diagnose_page
            diagnose_page(self.driver, "wa_no_practice_sets")

        return practice_sets

    def discover_chapters(self, practice_set_url):
        """Find quiz chapters/sections within a practice set."""
        _safe_get(self.driver, practice_set_url, "practice set")
        chapters = []

        try:
            # Look for chapter/section links
            selectors = [
                "a[href*='Chapter']",
                "a[href*='chapter']",
                "a[href*='Quiz']",
                "a[href*='quiz']",
                "a[href*='Question']",
                ".chapter-link",
                ".quiz-link",
                ".section-link",
            ]

            seen_urls = set()
            for selector in selectors:
                links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for link in links:
                    try:
                        href = link.get_attribute("href") or ""
                        if not href or href == "#" or href in seen_urls:
                            continue
                        name = link.text.strip()
                        if not name:
                            try:
                                parent = link.find_element(By.XPATH, "./..")
                                name = parent.text.strip()
                            except Exception:
                                name = href.split("/")[-1]
                        seen_urls.add(href)
                        chapters.append(Chapter(chapter_name=name, launch_url=href))
                    except StaleElementReferenceException:
                        continue

            # Fallback: look for "Launch", "Start", "Begin" links
            if not chapters:
                for link in self.driver.find_elements(By.TAG_NAME, "a"):
                    try:
                        text = link.text.strip().lower()
                        href = link.get_attribute("href") or ""
                        if any(kw in text for kw in ["launch", "start", "begin"]):
                            if href and href not in seen_urls:
                                # Try to get chapter name from surrounding context
                                name = ""
                                try:
                                    row = link.find_element(By.XPATH, "./ancestor::tr")
                                    name = row.text.replace(text, "").strip()
                                except NoSuchElementException:
                                    try:
                                        parent = link.find_element(By.XPATH, "./..")
                                        name = parent.text.replace(text, "").strip()
                                    except Exception:
                                        name = href
                                seen_urls.add(href)
                                chapters.append(Chapter(chapter_name=name, launch_url=href))
                    except StaleElementReferenceException:
                        continue

        except Exception as e:
            logger.error("Error discovering chapters: %s", e)

        logger.info("Found %d chapter(s)", len(chapters))
        for ch in chapters:
            logger.info("  - %s", ch.chapter_name)
        return chapters

    # ------------------------------------------------------------------
    # Question extraction
    # ------------------------------------------------------------------

    def get_total_questions(self, body_text):
        """Extract total question count from page text."""
        patterns = [
            r'Question\s+\d+\s+of\s+(\d+)',
            r'(\d+)\s+of\s+(\d+)\s+question',
            r'(\d+)\s+questions?\s+remaining',
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                return int(match.group(match.lastindex))
        return None

    def extract_question(self, body_text):
        """Extract question type and text from the page."""
        question_type = self._detect_type(body_text)
        question_text = self._extract_text(body_text)
        return question_type, question_text

    def extract_choices(self, body_text):
        """Extract answer choices from radio buttons or text."""
        choices = []

        # Try DOM-based extraction (radio buttons)
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

                    match = re.match(r'^([A-Da-d])[.)]\s*(.*)', label_text, re.DOTALL)
                    if match:
                        letter = match.group(1).upper()
                        text = match.group(2).strip()
                    else:
                        letter = chr(65 + len(choices))
                        text = label_text

                    choices.append({"label": letter, "text": text, "is_correct": False})
                except (StaleElementReferenceException, NoSuchElementException):
                    continue
        except Exception as e:
            logger.debug("Error extracting radio choices: %s", e)

        # Fallback: text-based extraction
        if not choices:
            choices = self._extract_choices_from_text(body_text)

        if not choices:
            logger.warning("  No answer choices found on page")
        return choices

    def submit_answer(self):
        """Select the first answer and submit."""
        try:
            # Click first visible radio button
            radios = self.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            for radio in radios:
                if radio.is_displayed() and radio.is_enabled():
                    _safe_click(self.driver, radio, "radio button")
                    break

            get_adaptive_delay().sleep("pre_submit")

            # Find and click submit button
            submit_btn = self._find_quiz_submit_button()
            if submit_btn:
                _safe_click(self.driver, submit_btn, "Submit button")
                get_adaptive_delay().sleep("post_submit")
            else:
                logger.warning("  Could not find Submit button")
                from scraper.browser import diagnose_page
                diagnose_page(self.driver, "wa_no_submit")
        except Exception as e:
            logger.warning("  Error submitting answer: %s", e)

    def extract_feedback(self, body_text):
        """Extract correct answer and explanation from post-submit feedback."""
        correct_answer = ""
        explanation = ""

        # Common patterns for correct answer
        patterns = [
            r'(?:correct|right)\s+answer\s+(?:is|was)\s+([A-D])',
            r'Answer:\s*([A-D])',
            r'([A-D])\s+is\s+(?:the\s+)?correct',
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                correct_answer = match.group(1).upper()
                break

        # Check for "Correct!" without explicit letter
        if not correct_answer:
            if re.search(r'\bCorrect[!.]', body_text) and "incorrect" not in body_text.lower():
                correct_answer = "A"  # Assumes first option was selected

        # Look for highlighted/marked correct choice in DOM
        if not correct_answer:
            try:
                correct_els = self.driver.find_elements(
                    By.CSS_SELECTOR, ".correct, .right-answer, [class*='correct']"
                )
                for el in correct_els:
                    text = el.text.strip()
                    match = re.match(r'^([A-D])[.)]\s', text)
                    if match:
                        correct_answer = match.group(1).upper()
                        break
            except Exception:
                pass

        # Extract explanation
        explanation_patterns = [
            r"(?:Explanation|Rationale|Feedback)[:\s]*(.+?)(?=\bNext\b|\bSubmit\b|$)",
            r"Here'?s\s+[Ww]hy:?\s*(.+?)(?=\bNext\b|\bSubmit\b|$)",
        ]
        for pattern in explanation_patterns:
            match = re.search(pattern, body_text, re.DOTALL | re.IGNORECASE)
            if match:
                explanation = match.group(1).strip()
                explanation = re.sub(r'\n\s*\n', '\n', explanation).strip()
                break

        if not correct_answer:
            logger.warning("  Could not determine correct answer from feedback")
        return correct_answer, explanation

    def click_next_question(self):
        """Navigate to the next question."""
        next_texts = ["next question", "next", "continue", ">>"]
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, "a, button, input[type='button']"):
                try:
                    text = (el.text or el.get_attribute("value") or "").strip().lower()
                    if any(nt in text for nt in next_texts):
                        if el.is_displayed() and el.is_enabled():
                            _safe_click(self.driver, el, "Next")
                            get_adaptive_delay().sleep("next_click")
                            return True
                except StaleElementReferenceException:
                    continue
        except Exception as e:
            logger.debug("Error clicking Next: %s", e)
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_quiz_submit_button(self):
        """Find the quiz submit/check answer button."""
        submit_texts = ["submit", "check answer", "check", "grade", "answer"]
        for el in self.driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], a.btn"):
            try:
                text = (el.text or el.get_attribute("value") or "").strip().lower()
                if any(st in text for st in submit_texts):
                    if el.is_displayed() and el.is_enabled():
                        return el
            except StaleElementReferenceException:
                continue
        return None

    @staticmethod
    def _detect_type(body_text):
        """Detect question type from page text."""
        if "Multiple Choice" in body_text or "multiple choice" in body_text.lower():
            return "Multiple Choice"
        if "True/False" in body_text or "True or False" in body_text:
            return "True/False"
        if "Fill in" in body_text or "fill in" in body_text.lower():
            return "Fill in the Blank"
        if "Select all" in body_text or "select all" in body_text.lower():
            return "Select All That Apply"
        if "Short Answer" in body_text or "short answer" in body_text.lower():
            return "Short Answer"
        if "Essay" in body_text:
            return "Essay"
        return "Multiple Choice"  # Default for West Academic Exam Pro

    @staticmethod
    def _extract_text(body_text):
        """Extract question text from page body."""
        try:
            text = body_text
            # Remove common headers/footers
            for marker in ["Question", ">>", "<<"]:
                if marker in text:
                    parts = text.split(marker, 1)
                    if len(parts) > 1 and len(parts[1].strip()) > 20:
                        text = parts[1].strip()
                        break

            lines = text.split("\n")
            question_lines = []
            for line in lines:
                stripped = line.strip()
                # Stop at answer choices
                if re.match(r'^[A-Da-d][.)]\s', stripped):
                    break
                if re.match(r'^[○●]\s*[A-Da-d][.)]\s', stripped):
                    break
                if not question_lines and not stripped:
                    continue
                # Skip type labels
                if stripped.lower() in (
                    "multiple choice", "true/false",
                    "fill in the blank", "select all that apply",
                    "short answer", "essay",
                ):
                    continue
                question_lines.append(stripped)

            result = " ".join(question_lines).strip()
            return re.sub(r'\s+', ' ', result)
        except Exception as e:
            logger.debug("Error extracting question text: %s", e)
            return ""

    @staticmethod
    def _extract_choices_from_text(body_text):
        """Extract answer choices from plain text using regex."""
        choices = []
        try:
            pattern = re.compile(
                r'([A-Da-d])[.)]\s+(.+?)(?=\n\s*[A-Da-d][.)]\s|\nSubmit|\nCheck|\Z)',
                re.DOTALL,
            )
            for label, text in pattern.findall(body_text):
                text = text.strip()
                if text and len(text) > 1:
                    choices.append({
                        "label": label.upper(),
                        "text": re.sub(r'\s+', ' ', text),
                        "is_correct": False,
                    })
        except Exception:
            pass
        return choices
