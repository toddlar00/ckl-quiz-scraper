"""Export scraped quiz data to JSON and CSV formats."""

import csv
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from scraper.quiz_scraper import Quiz

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "output"


def export_json(quizzes: list[Quiz], output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """Export quizzes to a JSON file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes.json")

    data = []
    for quiz in quizzes:
        quiz_data = {
            "title": quiz.title,
            "url": quiz.url,
            "question_count": len(quiz.questions),
            "questions": [],
        }
        for q in quiz.questions:
            quiz_data["questions"].append({
                "number": q.question_number,
                "question": q.question_text,
                "choices": q.choices,
                "correct_answer": q.correct_answer,
                "explanation": q.explanation,
                "source_url": q.source_url,
            })
        data.append(quiz_data)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Exported JSON to %s", filepath)
    return filepath


def export_csv(quizzes: list[Quiz], output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    """Export quizzes to a CSV file."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes.csv")

    fieldnames = [
        "quiz_title", "quiz_url", "question_number", "question_text",
        "choice_a", "choice_b", "choice_c", "choice_d",
        "correct_answer", "explanation", "source_url",
    ]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for quiz in quizzes:
            for q in quiz.questions:
                row = {
                    "quiz_title": quiz.title,
                    "quiz_url": quiz.url,
                    "question_number": q.question_number,
                    "question_text": q.question_text,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "source_url": q.source_url,
                }
                # Map choices to columns A-D
                for choice in q.choices:
                    label = choice.get("label", "").upper()
                    if label in ("A", "B", "C", "D"):
                        row[f"choice_{label.lower()}"] = choice.get("text", "")

                writer.writerow(row)

    logger.info("Exported CSV to %s", filepath)
    return filepath


def export_all(quizzes: list[Quiz], output_dir: str = DEFAULT_OUTPUT_DIR) -> dict:
    """Export quizzes to both JSON and CSV formats."""
    return {
        "json": export_json(quizzes, output_dir),
        "csv": export_csv(quizzes, output_dir),
    }
