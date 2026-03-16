"""Progress tracking for resume support.

Tracks chapter-level completion and question-level checkpoints so scraping
can resume after interruption without re-doing completed work.
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

PROGRESS_FILE = ".ckl_progress.json"


def _load_progress():
    """Load scraping progress from disk. Returns dict."""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Could not load progress file: %s", e)
        return {}


def _save_progress(data):
    """Save scraping progress to disk."""
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
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
    # Clear any partial checkpoint for this chapter
    checkpoints = progress.get("chapter_checkpoints", {})
    checkpoints.pop(chapter_url, None)
    progress["chapter_checkpoints"] = checkpoints
    _save_progress(progress)


def save_chapter_checkpoint(chapter_url, questions_scraped, questions_data):
    """Save a mid-chapter checkpoint for question-level resume.

    Called periodically during chapter scraping so that if the process
    is interrupted, it can resume from the last checkpoint instead of
    starting the chapter over.

    Args:
        chapter_url: The chapter's launch URL (unique key).
        questions_scraped: Number of questions scraped so far.
        questions_data: List of serializable question dicts.
    """
    progress = _load_progress()
    if "chapter_checkpoints" not in progress:
        progress["chapter_checkpoints"] = {}
    progress["chapter_checkpoints"][chapter_url] = {
        "questions_scraped": questions_scraped,
        "questions": questions_data,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_progress(progress)


def load_chapter_checkpoint(chapter_url):
    """Load a mid-chapter checkpoint if one exists.

    Returns:
        Tuple of (questions_scraped, questions_data) or (0, []) if no checkpoint.
    """
    progress = _load_progress()
    checkpoint = progress.get("chapter_checkpoints", {}).get(chapter_url)
    if checkpoint:
        logger.info(
            "  Resuming from checkpoint: %d questions already scraped",
            checkpoint["questions_scraped"],
        )
        return checkpoint["questions_scraped"], checkpoint["questions"]
    return 0, []


def clear_progress():
    """Delete the progress file to start fresh."""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        logger.info("Progress file cleared")
