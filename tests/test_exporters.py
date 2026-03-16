"""Tests for all quiz exporters."""

import csv
import json
import os
import zipfile
from xml.etree.ElementTree import parse as xml_parse

import pytest

from scraper.exporters import ALL_FORMATS, EXPORTERS, export_all
from scraper.exporters.anki import export_anki
from scraper.exporters.canvas_qti import export_canvas_qti
from scraper.exporters.csv_export import export_csv
from scraper.exporters.json_export import export_json
from scraper.exporters.kahoot import export_kahoot
from scraper.exporters.moodle_gift import export_moodle_gift
from scraper.exporters.moodle_xml import export_moodle_xml
from scraper.exporters.quizlet import export_quizlet


# ---- JSON Export ----

class TestJsonExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_json(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["practice_set"] == "Civil Procedure"
        assert len(data[0]["chapters"]) == 1
        assert len(data[0]["chapters"][0]["questions"]) == 2

    def test_question_fields(self, tmp_path, sample_practice_sets):
        path = export_json(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        q = data[0]["chapters"][0]["questions"][0]
        assert q["number"] == 1
        assert q["type"] == "Multiple Choice"
        assert q["correct_answer"] == "A"
        assert "de novo" in q["explanation"]
        assert len(q["choices"]) == 4
        assert any(c["is_correct"] for c in q["choices"])

    def test_choice_explanations(self, tmp_path, sample_practice_sets):
        path = export_json(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        q = data[0]["chapters"][0]["questions"][0]
        assert "choice_explanations" in q
        assert "A" in q["choice_explanations"]
        assert "Correct" in q["choice_explanations"]["A"]
        # Each choice dict also has explanation
        assert "explanation" in q["choices"][0]
        assert "Correct" in q["choices"][0]["explanation"]

    def test_empty_practice_sets(self, tmp_path, empty_practice_sets):
        path = export_json(empty_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data == []

    def test_creates_output_dir(self, tmp_path, sample_practice_sets):
        out = str(tmp_path / "nested" / "dir")
        path = export_json(sample_practice_sets, out)
        assert os.path.exists(path)


# ---- CSV Export ----

class TestCsvExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_csv(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_row_content(self, tmp_path, sample_practice_sets):
        path = export_csv(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["practice_set"] == "Civil Procedure"
        assert row["correct_answer"] == "A"
        assert row["choice_a"] == "De novo review"

    def test_has_all_columns(self, tmp_path, sample_practice_sets):
        path = export_csv(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        expected = {"practice_set", "chapter", "question_number", "total_questions",
                    "question_type", "question_text", "choice_a", "choice_b",
                    "choice_c", "choice_d", "correct_answer", "explanation",
                    "explanation_a", "explanation_b", "explanation_c", "explanation_d",
                    "source_url"}
        assert expected == set(row.keys())

    def test_per_choice_explanations(self, tmp_path, sample_practice_sets):
        path = export_csv(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert "Correct" in row["explanation_a"]
        assert "Incorrect" in row["explanation_b"]

    def test_empty_export(self, tmp_path, empty_practice_sets):
        path = export_csv(empty_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 0


# ---- Anki Export ----

class TestAnkiExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        # 3 header lines + 2 question lines
        assert len(lines) == 5

    def test_header_lines(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        assert lines[0].strip() == "#separator:tab"
        assert lines[1].strip() == "#html:true"
        assert lines[2].strip() == "#tags column:3"

    def test_card_has_three_fields(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        card_line = lines[3]  # First question
        fields = card_line.strip().split("\t")
        assert len(fields) == 3  # front, back, tags

    def test_front_contains_question(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        front = lines[3].split("\t")[0]
        assert "standard of review" in front
        assert "De novo" in front

    def test_back_contains_answer(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        back = lines[3].split("\t")[1]
        assert "Correct Answer: A" in back
        assert "de novo" in back

    def test_tags_contain_hierarchy(self, tmp_path, sample_practice_sets):
        path = export_anki(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        tags = lines[3].split("\t")[2]
        assert "CKL::" in tags


# ---- Quizlet Export ----

class TestQuizletExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_quizlet(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2

    def test_term_definition_format(self, tmp_path, sample_practice_sets):
        path = export_quizlet(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            line = f.readline()
        parts = line.strip().split("\t")
        assert len(parts) == 2
        term, definition = parts
        assert "standard of review" in term
        assert "Answer: A" in definition

    def test_no_tabs_in_content(self, tmp_path, sample_practice_sets):
        path = export_quizlet(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                assert len(parts) == 2  # Exactly one tab per line


# ---- Kahoot Export ----

class TestKahootExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_kahoot(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2

    def test_correct_answer_indexing(self, tmp_path, sample_practice_sets):
        path = export_kahoot(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        # Correct answer is A → index 1
        assert row["Correct answer(s)"] == "1"

    def test_answer_columns(self, tmp_path, sample_practice_sets):
        path = export_kahoot(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert row["Answer 1"] == "De novo review"
        assert row["Answer 2"] == "Abuse of discretion"
        assert row["Time limit (sec)"] == "60"

    def test_question_truncation(self, tmp_path, sample_practice_sets):
        path = export_kahoot(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert len(row["Question"]) <= 300

    def test_long_question_gets_ellipsis(self, tmp_path):
        """Questions over 300 chars should be truncated with ellipsis."""
        from scraper.models import QuizQuestion, Chapter, PracticeSet
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC",
            question_text="X" * 400,
            choices=[
                {"label": "A", "text": "One", "is_correct": True},
                {"label": "B", "text": "Two", "is_correct": False},
            ],
            correct_answer="A",
        )
        ch = Chapter(chapter_name="Ch1", launch_url="url", questions=[q])
        ps = [PracticeSet(title="Test", url="url", chapters=[ch])]
        path = export_kahoot(ps, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert len(row["Question"]) <= 300
        assert row["Question"].endswith("...")

    def test_long_answer_gets_ellipsis(self, tmp_path):
        """Answers over 75 chars should be truncated with ellipsis."""
        from scraper.models import QuizQuestion, Chapter, PracticeSet
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="MC",
            question_text="What?",
            choices=[
                {"label": "A", "text": "Y" * 100, "is_correct": True},
                {"label": "B", "text": "Short", "is_correct": False},
            ],
            correct_answer="A",
        )
        ch = Chapter(chapter_name="Ch1", launch_url="url", questions=[q])
        ps = [PracticeSet(title="Test", url="url", chapters=[ch])]
        path = export_kahoot(ps, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        assert len(row["Answer 1"]) <= 75
        assert row["Answer 1"].endswith("...")


# ---- Moodle GIFT Export ----

class TestMoodleGiftExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_moodle_gift(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        assert path.endswith(".gift")

    def test_contains_category(self, tmp_path, sample_practice_sets):
        path = export_moodle_gift(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "$CATEGORY:" in content
        assert "Civil Procedure" in content

    def test_correct_answer_marked(self, tmp_path, sample_practice_sets):
        path = export_moodle_gift(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "=De novo review" in content
        assert "~Abuse of discretion" in content

    def test_special_chars_escaped(self, tmp_path, special_chars_practice_sets):
        path = export_moodle_gift(special_chars_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # Special chars should be escaped
        assert "\\{" in content
        assert "\\}" in content
        assert "\\~" in content

    def test_question_structure(self, tmp_path, sample_practice_sets):
        path = export_moodle_gift(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "::CKL_Q1::" in content
        assert "{" in content
        assert "}" in content

    def test_essay_question_format(self, tmp_path):
        """Essay questions should use empty braces {}."""
        from scraper.models import QuizQuestion, Chapter, PracticeSet
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Essay",
            question_text="Discuss the concept of due process.",
        )
        ch = Chapter(chapter_name="Ch1", launch_url="url", questions=[q])
        ps = [PracticeSet(title="Test", url="url", chapters=[ch])]
        path = export_moodle_gift(ps, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "due process" in content
        assert "{}" in content  # Essay marker

    def test_short_answer_format(self, tmp_path):
        """Short answer questions should use {=answer} format."""
        from scraper.models import QuizQuestion, Chapter, PracticeSet
        q = QuizQuestion(
            question_number=1, total_questions=1,
            question_type="Short Answer",
            question_text="What is the capital of France?",
            correct_answer="Paris",
            explanation="Paris is the capital of France.",
        )
        ch = Chapter(chapter_name="Ch1", launch_url="url", questions=[q])
        ps = [PracticeSet(title="Test", url="url", chapters=[ch])]
        path = export_moodle_gift(ps, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "=Paris" in content


# ---- Moodle XML Export ----

class TestMoodleXmlExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_moodle_xml(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        assert path.endswith(".xml")

    def test_valid_xml(self, tmp_path, sample_practice_sets):
        path = export_moodle_xml(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "<?xml" in content
        assert "<quiz>" in content or "<quiz " in content

    def test_contains_questions(self, tmp_path, sample_practice_sets):
        path = export_moodle_xml(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "multichoice" in content
        assert "standard of review" in content

    def test_correct_answer_fraction(self, tmp_path, sample_practice_sets):
        path = export_moodle_xml(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert 'fraction="100"' in content
        assert 'fraction="0"' in content

    def test_category_elements(self, tmp_path, sample_practice_sets):
        path = export_moodle_xml(sample_practice_sets, str(tmp_path))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "CKL/Civil Procedure/" in content


# ---- Canvas QTI Export ----

class TestCanvasQtiExport:
    def test_basic_export(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        assert path.endswith(".zip")

    def test_zip_contents(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
        assert "imsmanifest.xml" in names
        assert "quiz_questions.xml" in names

    def test_manifest_valid_xml(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            manifest = zf.read("imsmanifest.xml").decode("utf-8")
        assert "<?xml" in manifest
        assert "manifest" in manifest
        assert "imsqti_xmlv1p2" in manifest

    def test_quiz_xml_has_questions(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            quiz = zf.read("quiz_questions.xml").decode("utf-8")
        assert "standard of review" in quiz
        assert "response_lid" in quiz
        assert "render_choice" in quiz

    def test_correct_answer_processing(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            quiz = zf.read("quiz_questions.xml").decode("utf-8")
        assert "varequal" in quiz
        assert "que_score" in quiz
        assert ">100<" in quiz

    def test_feedback_present(self, tmp_path, sample_practice_sets):
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            quiz = zf.read("quiz_questions.xml").decode("utf-8")
        assert "itemfeedback" in quiz
        assert "correct_fb" in quiz
        assert "incorrect_fb" in quiz

    def test_empty_export(self, tmp_path, empty_practice_sets):
        path = export_canvas_qti(empty_practice_sets, str(tmp_path))
        assert os.path.exists(path)
        with zipfile.ZipFile(path, "r") as zf:
            assert "imsmanifest.xml" in zf.namelist()

    def test_point_values_present(self, tmp_path, sample_practice_sets):
        """QTI export should include point values in metadata."""
        path = export_canvas_qti(sample_practice_sets, str(tmp_path))
        with zipfile.ZipFile(path, "r") as zf:
            quiz = zf.read("quiz_questions.xml").decode("utf-8")
        assert "points_possible" in quiz


# ---- Export Dispatcher ----

class TestExportDispatcher:
    def test_all_formats_registered(self):
        expected = {"json", "csv", "anki", "quizlet", "kahoot",
                    "moodle_gift", "moodle_xml", "canvas_qti"}
        assert set(ALL_FORMATS) == expected

    def test_export_all_default(self, tmp_path, sample_practice_sets):
        results = export_all(sample_practice_sets, str(tmp_path))
        assert len(results) == len(ALL_FORMATS)
        for fmt, path in results.items():
            assert os.path.exists(path), f"{fmt} file not created"

    def test_export_specific_formats(self, tmp_path, sample_practice_sets):
        results = export_all(sample_practice_sets, str(tmp_path), formats=["json", "csv"])
        assert set(results.keys()) == {"json", "csv"}

    def test_export_unknown_format_ignored(self, tmp_path, sample_practice_sets):
        results = export_all(sample_practice_sets, str(tmp_path), formats=["json", "nonexistent"])
        assert "json" in results
        assert "nonexistent" not in results
