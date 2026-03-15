"""Anki export — tab-separated text file importable into Anki.

Anki import format (TSV):
  Front<TAB>Back<TAB>Tags

Front side: question text + choices
Back side: correct answer + explanation
Tags: practice set and chapter for deck organization
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _sanitize_tag(text):
    """Convert text to a valid Anki tag (no spaces, limited special chars)."""
    tag = re.sub(r'[^a-zA-Z0-9_:-]', '_', text)
    return re.sub(r'_+', '_', tag).strip('_')


def export_anki(practice_sets, output_dir="output"):
    """Export to Anki-importable TSV file.

    In Anki, import with:
      - Type: "Basic (and reversed card)" or "Basic"
      - Field separator: Tab
      - Field 1 → Front, Field 2 → Back, Field 3 → Tags
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_anki.txt")

    with open(filepath, "w", encoding="utf-8") as f:
        # Anki recognizes this header comment
        f.write("#separator:tab\n")
        f.write("#html:true\n")
        f.write("#tags column:3\n")

        for ps in practice_sets:
            for ch in ps.chapters:
                for q in ch.questions:
                    front = _build_front(q)
                    back = _build_back(q)
                    tags = _build_tags(ps.title, ch.chapter_name)
                    # Anki TSV: fields separated by tabs, no tabs in content
                    f.write(f"{front}\t{back}\t{tags}\n")

    logger.info("Exported Anki: %s", filepath)
    return filepath


def _build_front(q):
    """Build the front of the Anki card (question + choices)."""
    lines = [f"<b>{q.question_type}</b><br><br>"] if q.question_type else []
    lines.append(q.question_text.replace("\n", "<br>"))
    lines.append("<br><br>")

    for choice in q.choices:
        lines.append(f"<b>{choice['label']}.</b> {choice['text']}<br>")

    return "".join(lines).replace("\t", " ")


def _build_back(q):
    """Build the back of the Anki card (answer + explanation)."""
    lines = []

    if q.correct_answer:
        lines.append(f"<b>Correct Answer: {q.correct_answer}</b><br><br>")

    if q.explanation:
        lines.append(f"<b>Explanation:</b><br>{q.explanation.replace(chr(10), '<br>')}")

    return "".join(lines).replace("\t", " ")


def _build_tags(ps_title, chapter_name):
    """Build Anki tags from practice set and chapter names."""
    ps_tag = _sanitize_tag(ps_title)
    ch_tag = _sanitize_tag(chapter_name)
    return f"CKL::{ps_tag} CKL::{ps_tag}::{ch_tag}"
