"""Export scraped CKL quiz data to JSON and CSV formats."""

import csv
import json
import logging
import os
from pathlib import Path

from scraper.quiz_scraper import PracticeSet

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "output"


def export_json(practice_sets: list[PracticeSet], output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """Export practice sets to a JSON file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes.json")

    data = []
    for ps in practice_sets:
        ps_data = {
            "practice_set": ps.title,
            "url": ps.url,
            "chapters": [],
        }
        for ch in ps.chapters:
            ch_data = {
                "chapter": ch.chapter_name,
                "launch_url": ch.launch_url,
                "status": ch.status,
                "question_count": len(ch.questions),
                "questions": [],
            }
            for q in ch.questions:
                ch_data["questions"].append({
                    "number": q.question_number,
                    "total": q.total_questions,
                    "type": q.question_type,
                    "question": q.question_text,
                    "choices": q.choices,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "source_url": q.source_url,
                })
            ps_data["chapters"].append(ch_data)
        data.append(ps_data)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Exported JSON to %s", filepath)
    return filepath


def export_csv(practice_sets: list[PracticeSet], output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """Export practice sets to a CSV file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes.csv")

    fieldnames = [
        "practice_set", "chapter", "question_number", "total_questions",
        "question_type", "question_text",
        "choice_a", "choice_b", "choice_c", "choice_d",
        "correct_answer", "explanation", "source_url",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for ps in practice_sets:
            for ch in ps.chapters:
                for q in ch.questions:
                    row = {
                        "practice_set": ps.title,
                        "chapter": ch.chapter_name,
                        "question_number": q.question_number,
                        "total_questions": q.total_questions,
                        "question_type": q.question_type,
                        "question_text": q.question_text,
                        "correct_answer": q.correct_answer,
                        "explanation": q.explanation,
                        "source_url": q.source_url,
                    }
                    for choice in q.choices:
                        label = choice.get("label", "").upper()
                        if label in ("A", "B", "C", "D"):
                            row[f"choice_{label.lower()}"] = choice.get("text", "")
                    writer.writerow(row)

    logger.info("Exported CSV to %s", filepath)
    return filepath


def export_all(practice_sets: list[PracticeSet], output_dir: str = DEFAULT_OUTPUT_DIR) -> dict:
    """Export to both JSON and CSV formats."""
    return {
        "json": export_json(practice_sets, output_dir),
        "csv": export_csv(practice_sets, output_dir),
    }
