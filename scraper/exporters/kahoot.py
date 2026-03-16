"""Kahoot export — Excel-compatible CSV matching the Kahoot quiz template.

Kahoot spreadsheet import columns:
  Question, Answer 1, Answer 2, Answer 3, Answer 4,
  Time limit (sec), Correct answer(s)

The "Correct answer(s)" column uses 1-based index (1=Answer 1, 2=Answer 2, etc.)
Questions have a 120-char limit for display, but the full text is preserved here.
"""

import csv
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ANSWER_INDEX = {"A": 1, "B": 2, "C": 3, "D": 4}

# Kahoot limits
QUESTION_MAX_LENGTH = 300
ANSWER_MAX_LENGTH = 75


def export_kahoot(practice_sets, output_dir="output"):
    """Export to Kahoot-importable spreadsheet (CSV).

    In Kahoot: Create -> Import spreadsheet -> upload this CSV.
    Logs warnings when content is truncated.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_kahoot.csv")

    fieldnames = [
        "Question",
        "Answer 1", "Answer 2", "Answer 3", "Answer 4",
        "Time limit (sec)",
        "Correct answer(s)",
    ]

    truncation_count = 0

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for ps in practice_sets:
            for ch in ps.chapters:
                for q in ch.questions:
                    question_text = q.question_text
                    if len(question_text) > QUESTION_MAX_LENGTH:
                        truncation_count += 1
                        question_text = question_text[:QUESTION_MAX_LENGTH - 3] + "..."

                    row = {
                        "Question": question_text,
                        "Answer 1": "",
                        "Answer 2": "",
                        "Answer 3": "",
                        "Answer 4": "",
                        "Time limit (sec)": 60,
                        "Correct answer(s)": "",
                    }

                    for choice in q.choices:
                        idx = ANSWER_INDEX.get(choice["label"])
                        if idx:
                            answer_text = choice["text"]
                            if len(answer_text) > ANSWER_MAX_LENGTH:
                                truncation_count += 1
                                answer_text = answer_text[:ANSWER_MAX_LENGTH - 3] + "..."
                            row[f"Answer {idx}"] = answer_text

                    if q.correct_answer:
                        correct_idx = ANSWER_INDEX.get(q.correct_answer[0])
                        if correct_idx:
                            row["Correct answer(s)"] = correct_idx

                    writer.writerow(row)

    if truncation_count > 0:
        logger.warning(
            "Kahoot export: %d field(s) truncated (question max %d chars, answer max %d chars)",
            truncation_count, QUESTION_MAX_LENGTH, ANSWER_MAX_LENGTH,
        )

    logger.info("Exported Kahoot: %s", filepath)
    return filepath
