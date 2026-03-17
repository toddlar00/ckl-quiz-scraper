"""Site mapper — discovers and documents full website structure before scraping.

Performs a read-only crawl of the quiz site to build a complete map:
  - All practice sets (books)
  - All chapters within each practice set
  - Question counts and types per chapter (by peeking at the first page)
  - Page structure signatures (DOM elements, navigation patterns)

The map is cached to disk so subsequent runs can skip the discovery phase.
Run with --map to generate the map without scraping.
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field

from selenium.webdriver.common.by import By

from scraper.layout_learner import analyze_page, detect_question_type
from scraper.quiz_scraper import _get_body_text, _safe_get

logger = logging.getLogger(__name__)

SITE_MAP_FILE = ".ckl_site_map.json"


@dataclass
class ChapterInfo:
    """Discovered metadata about a single chapter."""
    name: str = ""
    launch_url: str = ""
    status: str = ""
    total_questions: int = 0
    question_types: list = field(default_factory=list)
    has_preamble: bool = False
    has_radio_buttons: bool = False
    has_checkboxes: bool = False
    has_text_input: bool = False
    sample_question: str = ""


@dataclass
class PracticeSetInfo:
    """Discovered metadata about a practice set."""
    title: str = ""
    url: str = ""
    chapters: list = field(default_factory=list)
    total_chapters: int = 0
    total_questions: int = 0


@dataclass
class SiteMap:
    """Complete structural map of a quiz website."""
    site_name: str = ""
    base_url: str = ""
    mapped_at: str = ""
    practice_sets: list = field(default_factory=list)
    total_practice_sets: int = 0
    total_chapters: int = 0
    total_questions: int = 0
    question_type_summary: dict = field(default_factory=dict)

    def save(self, path=None):
        """Persist the site map to disk."""
        path = path or SITE_MAP_FILE
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        logger.info("Site map saved to %s", path)

    @classmethod
    def load(cls, path=None):
        """Load a previously saved site map."""
        path = path or SITE_MAP_FILE
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            site_map = cls()
            for k, v in data.items():
                if k in cls.__dataclass_fields__:
                    setattr(site_map, k, v)
            logger.info("Loaded site map from %s (%d practice sets, %d chapters)",
                        path, site_map.total_practice_sets, site_map.total_chapters)
            return site_map
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Could not load site map: %s", e)
            return None

    def print_summary(self):
        """Print a formatted summary of the site map."""
        print(f"\n{'=' * 70}")
        print(f"  SITE MAP: {self.site_name}")
        print(f"  {self.base_url}")
        print(f"{'=' * 70}")
        print(f"  Practice Sets: {self.total_practice_sets}")
        print(f"  Chapters:      {self.total_chapters}")
        print(f"  Questions:     {self.total_questions}")

        if self.question_type_summary:
            print(f"\n  Question Types:")
            for qtype, count in sorted(self.question_type_summary.items(),
                                       key=lambda x: -x[1]):
                pct = (count / self.total_questions * 100) if self.total_questions else 0
                print(f"    {qtype:<30s} {count:>4d}  ({pct:.0f}%)")

        for ps_info in self.practice_sets:
            ps_questions = ps_info.get("total_questions", 0) if isinstance(ps_info, dict) else ps_info.total_questions
            ps_title = ps_info.get("title", "") if isinstance(ps_info, dict) else ps_info.title
            ps_chapters = ps_info.get("chapters", []) if isinstance(ps_info, dict) else ps_info.chapters
            print(f"\n  {'─' * 66}")
            print(f"  {ps_title}  ({len(ps_chapters)} chapters, {ps_questions} questions)")
            print(f"  {'─' * 66}")

            for ch in ps_chapters:
                if isinstance(ch, dict):
                    ch_name = ch.get("name", "")
                    ch_total = ch.get("total_questions", 0)
                    ch_status = ch.get("status", "")
                    ch_types = ch.get("question_types", [])
                    ch_preamble = ch.get("has_preamble", False)
                else:
                    ch_name = ch.name
                    ch_total = ch.total_questions
                    ch_status = ch.status
                    ch_types = ch.question_types
                    ch_preamble = ch.has_preamble

                status_tag = f" [{ch_status}]" if ch_status else ""
                preamble_tag = " (has preamble)" if ch_preamble else ""
                types_str = ", ".join(sorted(set(ch_types))) if ch_types else "unknown"
                print(f"    {ch_name:<45s} {ch_total:>3d} q  {status_tag}")
                print(f"      Types: {types_str}{preamble_tag}")

        print(f"\n{'=' * 70}\n")


def map_site(driver, site_scraper, peek_chapters=True):
    """Map the full website structure.

    Discovers all practice sets and chapters. Optionally peeks into each
    chapter to determine question counts and types without full scraping.

    Args:
        driver: Selenium WebDriver (logged in).
        site_scraper: BaseScraper instance.
        peek_chapters: If True, navigate into each chapter to read question
                       count and type from the first page.

    Returns:
        SiteMap with the full discovered structure.
    """
    site_map = SiteMap(
        site_name=site_scraper.SITE_NAME,
        base_url=site_scraper.BASE_URL,
        mapped_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Discover practice sets
    logger.info("Mapping site structure...")
    ps_links = site_scraper.discover_practice_sets()

    if not ps_links:
        logger.warning("No practice sets found during mapping")
        return site_map

    type_totals = {}

    for ps_idx, (ps_title, ps_url) in enumerate(ps_links, 1):
        logger.info("[%d/%d] Mapping practice set: %s", ps_idx, len(ps_links), ps_title)

        ps_info = PracticeSetInfo(title=ps_title, url=ps_url)

        # Discover chapters
        chapters = site_scraper.discover_chapters(ps_url)
        ps_info.total_chapters = len(chapters)

        for ch_idx, chapter in enumerate(chapters, 1):
            ch_info = ChapterInfo(
                name=chapter.chapter_name,
                launch_url=chapter.launch_url,
                status=chapter.status,
            )

            if peek_chapters:
                logger.info("  [%d/%d] Peeking at: %s",
                            ch_idx, len(chapters), chapter.chapter_name)
                _peek_chapter(driver, site_scraper, ch_info, type_totals)

            ps_info.chapters.append(asdict(ch_info))
            ps_info.total_questions += ch_info.total_questions

        site_map.practice_sets.append(asdict(ps_info))

    # Aggregate totals
    site_map.total_practice_sets = len(site_map.practice_sets)
    site_map.total_chapters = sum(
        ps["total_chapters"] if isinstance(ps, dict) else ps.total_chapters
        for ps in site_map.practice_sets
    )
    site_map.total_questions = sum(
        ps["total_questions"] if isinstance(ps, dict) else ps.total_questions
        for ps in site_map.practice_sets
    )
    site_map.question_type_summary = type_totals

    site_map.save()
    return site_map


def _peek_chapter(driver, site_scraper, ch_info, type_totals):
    """Navigate into a chapter to read question count and type without scraping.

    Reads the first page only — does not submit answers or advance.
    Navigates back to the practice set page afterward.

    Args:
        driver: Selenium WebDriver.
        site_scraper: BaseScraper instance (for prepare_chapter).
        ch_info: ChapterInfo to populate.
        type_totals: Dict to accumulate question type counts across chapters.
    """
    try:
        _safe_get(driver, ch_info.launch_url, f"chapter peek: {ch_info.name}")

        # Check for preamble pages
        body_text = _get_body_text(driver)
        has_preamble = (
            "Continue" in body_text
            and not driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
        )
        ch_info.has_preamble = has_preamble

        # Click through preamble to reach actual questions
        if has_preamble:
            site_scraper.prepare_chapter()
            body_text = _get_body_text(driver)

        # Extract question count from "Question X of Y"
        match = re.search(r'Question\s+\d+\s+of\s+(\d+)', body_text, re.IGNORECASE)
        if match:
            ch_info.total_questions = int(match.group(1))
        else:
            match = re.search(r'(\d+)\s+of\s+(\d+)', body_text)
            if match:
                ch_info.total_questions = int(match.group(2))

        # Detect question type from first page
        qtype = detect_question_type(body_text)
        if qtype:
            ch_info.question_types.append(qtype)
            type_totals[qtype] = type_totals.get(qtype, 0) + ch_info.total_questions

        # Analyze page structure
        sig = analyze_page(driver)
        ch_info.has_radio_buttons = sig.has_radio_buttons
        ch_info.has_checkboxes = sig.has_checkboxes
        ch_info.has_text_input = sig.has_text_input

        # Grab first question text as sample
        from scraper.sites.ckl import CKLScraper
        if isinstance(site_scraper, CKLScraper):
            sample = CKLScraper._extract_text(body_text)
            if sample:
                ch_info.sample_question = sample[:120]

        logger.info("    %d questions, type: %s",
                     ch_info.total_questions, qtype or "unknown")

    except Exception as e:
        logger.warning("    Could not peek at chapter: %s", e)

    # Navigate back (go to the practice set page via browser back)
    try:
        driver.back()
        time.sleep(1)
    except Exception:
        pass
