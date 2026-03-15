"""Quizlet export — tab-separated file for Quizlet import.

Quizlet import format:
  Term<TAB>Definition

One card per line. We put the question on the term side and
the answer + explanation on the definition side.
Quizlet also supports custom delimiters during import.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def export_quizlet(practice_sets, output_dir="output"):
    """Export to Quizlet-importable TSV file.

    In Quizlet: Create Set → Import → paste or upload this file.
    Set "Between term and definition" to Tab, "Between rows" to New line.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_quizlet.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        for ps in practice_sets:
            for ch in ps.chapters:
                for q in ch.questions:
                    term = _build_term(q)
                    definition = _build_definition(q)
                    f.write(f"{term}\t{definition}\n")

    logger.info("Exported Quizlet: %s", filepath)
    return filepath


def _build_term(q):
    """Build the term (question side) for Quizlet."""
    parts = [q.question_text]
    if q.choices:
        parts.append("")
        for choice in q.choices:
            parts.append(f"{choice['label']}. {choice['text']}")
    return " | ".join(parts).replace("\t", " ").replace("\n", " | ")


def _build_definition(q):
    """Build the definition (answer side) for Quizlet."""
    parts = []
    if q.correct_answer:
        parts.append(f"Answer: {q.correct_answer}")
    if q.explanation:
        parts.append(q.explanation)
    # Per-choice explanations
    for choice in q.choices:
        expl = choice.get("explanation", "")
        if expl:
            label = choice.get("label", "")
            parts.append(f"{label}: {expl}")
    return " | ".join(parts).replace("\t", " ").replace("\n", " | ")
