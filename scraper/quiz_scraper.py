"""Quiz discovery and scraping logic."""

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scraper import config

logger = logging.getLogger(__name__)


@dataclass
class QuizQuestion:
    """Represents a single quiz question with its answers and explanation."""
    question_number: int
    question_text: str
    choices: list[dict] = field(default_factory=list)  # [{"label": "A", "text": "...", "is_correct": bool}]
    correct_answer: str = ""
    explanation: str = ""
    source_url: str = ""


@dataclass
class Quiz:
    """Represents a quiz containing multiple questions."""
    title: str
    url: str
    questions: list[QuizQuestion] = field(default_factory=list)


def discover_quiz_links(driver):
    """Find all quiz-related links on the current site.

    Navigates through the site looking for pages containing quizzes.
    Returns a list of (title, url) tuples.
    """
    base = config.BASE_URL.rstrip("/")
    quiz_links = []
    visited = set()

    # Common paths where quizzes might be found
    discovery_paths = [
        "/",
        "/quizzes",
        "/quiz",
        "/courses",
        "/my-courses",
        "/dashboard",
        "/lessons",
        "/modules",
        "/practice",
        "/assessments",
        "/exams",
    ]

    for path in discovery_paths:
        url = base + path
        if url in visited:
            continue
        visited.add(url)
        try:
            driver.get(url)
            time.sleep(2)
            found = _extract_quiz_links(driver, base)
            for link in found:
                if link not in quiz_links:
                    quiz_links.append(link)
        except Exception as e:
            logger.debug("Could not access %s: %s", url, e)

    # Also search by crawling links on visited pages
    if not quiz_links:
        quiz_links = _crawl_for_quizzes(driver, base, visited)

    logger.info("Discovered %d quiz link(s)", len(quiz_links))
    return quiz_links


def _extract_quiz_links(driver, base_url):
    """Extract quiz-related links from the current page."""
    quiz_keywords = [
        "quiz", "test", "exam", "assessment", "practice",
        "question", "review", "attempt",
    ]
    links = []

    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
        for anchor in anchors:
            href = anchor.get_attribute("href") or ""
            text = anchor.text.strip()
            if not href or href.startswith("javascript:") or href == "#":
                continue
            href_lower = href.lower()
            text_lower = text.lower()
            if any(kw in href_lower or kw in text_lower for kw in quiz_keywords):
                full_url = urljoin(base_url, href)
                if full_url.startswith(base_url):
                    links.append((text or full_url, full_url))
    except Exception as e:
        logger.debug("Error extracting links: %s", e)

    return links


def _crawl_for_quizzes(driver, base_url, visited, max_pages=20):
    """Crawl site pages looking for quiz content."""
    quiz_links = []
    to_visit = []

    # Gather internal links from current page
    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
        for anchor in anchors:
            href = anchor.get_attribute("href") or ""
            if href.startswith(base_url) and href not in visited:
                to_visit.append(href)
    except Exception:
        pass

    pages_checked = 0
    for url in to_visit:
        if pages_checked >= max_pages:
            break
        if url in visited:
            continue
        visited.add(url)
        pages_checked += 1

        try:
            driver.get(url)
            time.sleep(1)
            found = _extract_quiz_links(driver, base_url)
            for link in found:
                if link not in quiz_links:
                    quiz_links.append(link)

            # Check if current page itself is a quiz
            if _page_has_quiz_content(driver):
                title = driver.title or url
                quiz_links.append((title, url))
        except Exception:
            continue

    return quiz_links


def _page_has_quiz_content(driver):
    """Check if the current page contains quiz question content."""
    quiz_indicators = [
        ".quiz", ".question", ".quiz-question", ".exam-question",
        "[class*='quiz']", "[class*='question']", "[id*='quiz']",
        "form.quiz", ".quiz-form", ".quiz-content",
    ]
    for selector in quiz_indicators:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if elements:
                return True
        except Exception:
            continue
    return False


def scrape_quiz(driver, quiz_url, quiz_title=""):
    """Scrape all questions from a quiz page.

    Handles both single-page quizzes and multi-page/paginated quizzes.
    """
    driver.get(quiz_url)
    time.sleep(3)

    title = quiz_title or driver.title or "Untitled Quiz"
    quiz = Quiz(title=title, url=quiz_url)

    # Try to scrape questions from the current page
    questions = _scrape_questions_from_page(driver, quiz_url)
    quiz.questions.extend(questions)

    # Check for pagination / "next" buttons
    page_num = 1
    while True:
        next_btn = _find_next_button(driver)
        if not next_btn:
            break
        try:
            next_btn.click()
            time.sleep(2)
            page_num += 1
            more_questions = _scrape_questions_from_page(
                driver, quiz_url, start_num=len(quiz.questions) + 1
            )
            if not more_questions:
                break
            quiz.questions.extend(more_questions)
        except Exception as e:
            logger.warning("Error navigating to next page: %s", e)
            break

    logger.info(
        "Scraped %d question(s) from quiz: %s",
        len(quiz.questions), quiz.title
    )
    return quiz


def _scrape_questions_from_page(driver, source_url, start_num=1):
    """Extract quiz questions from the current page."""
    questions = []

    # Strategy 1: Look for structured question containers
    question_containers = _find_question_containers(driver)
    if question_containers:
        for i, container in enumerate(question_containers):
            q = _parse_question_container(container, start_num + i, source_url)
            if q:
                questions.append(q)
        return questions

    # Strategy 2: Look for question patterns in the page text
    questions = _parse_questions_from_text(driver, source_url, start_num)
    return questions


def _find_question_containers(driver):
    """Find DOM elements that contain individual questions."""
    container_selectors = [
        ".quiz-question",
        ".question",
        ".question-container",
        ".question-wrapper",
        ".quiz-item",
        ".exam-question",
        "[class*='question-']",
        ".wpProQuiz_question",
        ".ld-question",
        ".sfwd-question",
        "div[data-question]",
        ".quiz_question",
        ".problem",
        ".assessment-question",
    ]
    for selector in container_selectors:
        try:
            containers = driver.find_elements(By.CSS_SELECTOR, selector)
            if containers:
                return containers
        except Exception:
            continue
    return []


def _parse_question_container(container, question_num, source_url):
    """Parse a question from a DOM container element."""
    try:
        # Extract question text
        question_text = ""
        q_text_selectors = [
            ".question-text", ".question-title", ".question_text",
            ".wpProQuiz_question_text", ".ld-question-text",
            "h3", "h4", "p.question", ".question-content",
        ]
        for selector in q_text_selectors:
            els = container.find_elements(By.CSS_SELECTOR, selector)
            if els and els[0].text.strip():
                question_text = els[0].text.strip()
                break

        if not question_text:
            # Try getting the first meaningful text from the container
            all_text = container.text.strip()
            if all_text:
                lines = all_text.split("\n")
                question_text = lines[0].strip()

        if not question_text:
            return None

        question = QuizQuestion(
            question_number=question_num,
            question_text=question_text,
            source_url=source_url,
        )

        # Extract answer choices
        choice_selectors = [
            ".answer", ".choice", ".option", ".quiz-answer",
            "li", ".wpProQuiz_questionListItem",
            "label", ".answer-option", ".quiz-option",
            "input[type='radio'] + label",
            "input[type='radio'] + span",
        ]
        for selector in choice_selectors:
            choices_els = container.find_elements(By.CSS_SELECTOR, selector)
            if len(choices_els) >= 2:
                for j, choice_el in enumerate(choices_els):
                    choice_text = choice_el.text.strip()
                    if not choice_text:
                        continue

                    is_correct = _is_correct_answer(choice_el)
                    label = chr(65 + j)  # A, B, C, D...

                    question.choices.append({
                        "label": label,
                        "text": choice_text,
                        "is_correct": is_correct,
                    })

                    if is_correct:
                        question.correct_answer = f"{label}. {choice_text}"
                break

        # Extract explanation
        explanation_selectors = [
            ".explanation", ".answer-explanation", ".quiz-explanation",
            ".wpProQuiz_response", ".feedback", ".rationale",
            ".answer-feedback", ".solution", ".correct-response",
            "[class*='explanation']", "[class*='feedback']",
        ]
        for selector in explanation_selectors:
            expl_els = container.find_elements(By.CSS_SELECTOR, selector)
            if expl_els:
                explanation_text = expl_els[0].text.strip()
                if explanation_text:
                    question.explanation = explanation_text
                    break

        return question

    except Exception as e:
        logger.debug("Error parsing question container: %s", e)
        return None


def _is_correct_answer(element):
    """Determine if an answer choice element is marked as correct."""
    try:
        classes = element.get_attribute("class") or ""
        correct_indicators = ["correct", "right", "selected", "active", "success"]
        if any(ind in classes.lower() for ind in correct_indicators):
            return True

        # Check for a checkmark or correct icon
        icons = element.find_elements(
            By.CSS_SELECTOR, ".correct-icon, .check, .fa-check, .dashicons-yes"
        )
        if icons:
            return True

        # Check data attributes
        data_correct = element.get_attribute("data-correct")
        if data_correct and data_correct.lower() in ("true", "1", "yes"):
            return True

    except Exception:
        pass
    return False


def _parse_questions_from_text(driver, source_url, start_num=1):
    """Fallback: parse questions from raw page text using regex patterns."""
    questions = []
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text

        # Pattern: numbered questions like "1. What is..." or "Question 1:"
        q_pattern = re.compile(
            r'(?:^|\n)\s*(?:Question\s+)?(\d+)[.):]\s*(.+?)(?=\n\s*(?:Question\s+)?\d+[.):]\s|\Z)',
            re.DOTALL | re.IGNORECASE
        )

        matches = q_pattern.findall(body_text)
        for i, (num, text) in enumerate(matches):
            text = text.strip()
            if len(text) < 10:
                continue

            question = QuizQuestion(
                question_number=start_num + i,
                question_text=text.split("\n")[0].strip(),
                source_url=source_url,
            )

            # Try to extract choices (A. ... B. ... C. ... D. ...)
            choice_pattern = re.compile(r'([A-D])[.)]\s*(.+?)(?=[A-D][.)]\s|$)', re.DOTALL)
            choice_matches = choice_pattern.findall(text)
            for label, choice_text in choice_matches:
                question.choices.append({
                    "label": label,
                    "text": choice_text.strip(),
                    "is_correct": False,
                })

            questions.append(question)

    except Exception as e:
        logger.debug("Error parsing text for questions: %s", e)

    return questions


def _find_next_button(driver):
    """Find a 'Next' or pagination button on the current page."""
    next_selectors = [
        "button.next", "a.next", ".next-btn", "#next-btn",
        "button.quiz-next", ".quiz-next-btn",
        "[class*='next']", "a[rel='next']",
    ]
    next_keywords = ["next", "continue", ">>", "next question"]

    for selector in next_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    return el
        except Exception:
            continue

    # Search by button/link text
    try:
        buttons = driver.find_elements(
            By.CSS_SELECTOR, "button, a.btn, input[type='button'], input[type='submit']"
        )
        for btn in buttons:
            text = btn.text.strip().lower()
            if text in next_keywords and btn.is_displayed() and btn.is_enabled():
                return btn
    except Exception:
        pass

    return None


def scrape_quiz_results(driver, quiz_url):
    """Scrape quiz results/review page where answers and explanations are shown.

    Many quiz platforms show correct answers only after submission on a results page.
    """
    driver.get(quiz_url)
    time.sleep(3)

    # Look for "review" or "results" links/buttons
    review_selectors = [
        "a[href*='review']", "a[href*='result']",
        "button.review", ".review-btn", ".view-results",
        ".quiz-results", ".quiz-review",
    ]
    for selector in review_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed():
                    el.click()
                    time.sleep(3)
                    break
        except Exception:
            continue

    return scrape_quiz(driver, driver.current_url)
