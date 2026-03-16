"""Tests for progress tracking and checkpointing."""

import json
import os

import pytest

from scraper.progress import (
    _load_progress,
    _save_progress,
    clear_progress,
    is_chapter_completed,
    load_chapter_checkpoint,
    mark_chapter_completed,
    save_chapter_checkpoint,
)


@pytest.fixture(autouse=True)
def isolate_progress_file(tmp_path, monkeypatch):
    """Use a temp directory for progress files."""
    progress_file = str(tmp_path / "test_progress.json")
    monkeypatch.setattr("scraper.progress.PROGRESS_FILE", progress_file)


class TestProgressTracking:
    def test_empty_progress_on_start(self):
        assert _load_progress() == {}

    def test_mark_chapter_completed(self):
        mark_chapter_completed("http://example.com/ch1", 10)
        assert is_chapter_completed("http://example.com/ch1")

    def test_chapter_not_completed(self):
        assert not is_chapter_completed("http://example.com/ch1")

    def test_multiple_chapters(self):
        mark_chapter_completed("http://example.com/ch1", 10)
        mark_chapter_completed("http://example.com/ch2", 5)
        assert is_chapter_completed("http://example.com/ch1")
        assert is_chapter_completed("http://example.com/ch2")
        assert not is_chapter_completed("http://example.com/ch3")

    def test_clear_progress(self):
        mark_chapter_completed("http://example.com/ch1", 10)
        clear_progress()
        assert not is_chapter_completed("http://example.com/ch1")

    def test_completed_chapter_has_question_count(self):
        mark_chapter_completed("http://example.com/ch1", 15)
        progress = _load_progress()
        entry = progress["completed_chapters"]["http://example.com/ch1"]
        assert entry["question_count"] == 15
        assert "timestamp" in entry


class TestQuestionCheckpoints:
    def test_no_checkpoint_returns_zero(self):
        offset, data = load_chapter_checkpoint("http://example.com/ch1")
        assert offset == 0
        assert data == []

    def test_save_and_load_checkpoint(self):
        questions = [
            {"question_number": 1, "question_text": "Q1"},
            {"question_number": 2, "question_text": "Q2"},
        ]
        save_chapter_checkpoint("http://example.com/ch1", 2, questions)
        offset, data = load_chapter_checkpoint("http://example.com/ch1")
        assert offset == 2
        assert len(data) == 2
        assert data[0]["question_text"] == "Q1"

    def test_checkpoint_cleared_on_completion(self):
        questions = [{"question_number": 1, "question_text": "Q1"}]
        save_chapter_checkpoint("http://example.com/ch1", 1, questions)
        # Marking completed should clear the checkpoint
        mark_chapter_completed("http://example.com/ch1", 5)
        offset, data = load_chapter_checkpoint("http://example.com/ch1")
        assert offset == 0
        assert data == []

    def test_checkpoint_updates(self):
        q1 = [{"question_number": 1, "question_text": "Q1"}]
        save_chapter_checkpoint("http://example.com/ch1", 1, q1)

        q2 = [
            {"question_number": 1, "question_text": "Q1"},
            {"question_number": 2, "question_text": "Q2"},
            {"question_number": 3, "question_text": "Q3"},
        ]
        save_chapter_checkpoint("http://example.com/ch1", 3, q2)

        offset, data = load_chapter_checkpoint("http://example.com/ch1")
        assert offset == 3
        assert len(data) == 3

    def test_independent_checkpoints(self):
        save_chapter_checkpoint("http://example.com/ch1", 2, [{"q": 1}, {"q": 2}])
        save_chapter_checkpoint("http://example.com/ch2", 1, [{"q": 1}])

        off1, data1 = load_chapter_checkpoint("http://example.com/ch1")
        off2, data2 = load_chapter_checkpoint("http://example.com/ch2")
        assert off1 == 2
        assert off2 == 1


class TestProgressFileCorruption:
    def test_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        progress_file = str(tmp_path / "corrupt.json")
        monkeypatch.setattr("scraper.progress.PROGRESS_FILE", progress_file)
        with open(progress_file, "w") as f:
            f.write("{not valid json")
        assert _load_progress() == {}

    def test_nonexistent_directory(self, tmp_path, monkeypatch):
        progress_file = str(tmp_path / "nonexistent" / "dir" / "progress.json")
        monkeypatch.setattr("scraper.progress.PROGRESS_FILE", progress_file)
        # Should not raise — save silently fails
        _save_progress({"test": True})
