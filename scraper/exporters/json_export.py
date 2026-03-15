"""JSON export."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def export_json(practice_sets, output_dir="output"):
    """Export practice sets to a structured JSON file."""
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
                    "choice_explanations": q.choice_explanations,
                    "source_url": q.source_url,
                })
            ps_data["chapters"].append(ch_data)
        data.append(ps_data)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Exported JSON: %s", filepath)
    return filepath
