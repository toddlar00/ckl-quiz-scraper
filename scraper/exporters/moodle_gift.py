"""Moodle GIFT format export.

GIFT format reference:
  ::Title:: Question text {
    =Correct answer#Feedback for correct
    ~Wrong answer 1#Feedback for wrong 1
    ~Wrong answer 2#Feedback for wrong 2
    ~Wrong answer 3#Feedback for wrong 3
  }

Special characters (= ~ # { } :) must be escaped with backslash in text.
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _escape_gift(text):
    """Escape special GIFT characters."""
    for ch in ("\\", "~", "=", "#", "{", "}", ":"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", "\\n")


def export_moodle_gift(practice_sets, output_dir="output"):
    """Export to Moodle GIFT format (.gift file).

    In Moodle: Question bank → Import → GIFT format → upload this file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_moodle.gift")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("// CKL Quiz Export - Moodle GIFT format\n\n")

        question_id = 0
        for ps in practice_sets:
            f.write(f"// Practice Set: {ps.title}\n")
            for ch in ps.chapters:
                f.write(f"// {ch.chapter_name}\n")
                category = f"$CATEGORY: CKL/{_escape_gift(ps.title)}/{_escape_gift(ch.chapter_name)}\n\n"
                f.write(category)

                for q in ch.questions:
                    question_id += 1
                    title = f"CKL_Q{question_id}"
                    q_text = _escape_gift(q.question_text)
                    explanation = _escape_gift(q.explanation) if q.explanation else ""

                    f.write(f"::{title}::{q_text} {{\n")

                    for choice in q.choices:
                        c_text = _escape_gift(choice["text"])
                        is_correct = choice.get("is_correct", False)
                        prefix = "=" if is_correct else "~"

                        if is_correct and explanation:
                            f.write(f"  {prefix}{c_text}#{explanation}\n")
                        elif not is_correct and explanation:
                            f.write(f"  {prefix}{c_text}#{explanation}\n")
                        else:
                            f.write(f"  {prefix}{c_text}\n")

                    f.write("}\n\n")

    logger.info("Exported Moodle GIFT: %s", filepath)
    return filepath
