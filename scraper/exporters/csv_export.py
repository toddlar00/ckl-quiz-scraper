"""CSV export."""

import csv
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def export_csv(practice_sets, output_dir="output"):
    """Export practice sets to a flat CSV file (one row per question)."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes.csv")

    fieldnames = [
        "practice_set", "chapter", "question_number", "total_questions",
        "question_type", "question_text",
        "choice_a", "choice_b", "choice_c", "choice_d",
        "correct_answer", "explanation",
        "explanation_a", "explanation_b", "explanation_c", "explanation_d",
        "source_url",
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
                            row[f"explanation_{label.lower()}"] = choice.get("explanation", "")
                    writer.writerow(row)

    logger.info("Exported CSV: %s", filepath)
    return filepath
