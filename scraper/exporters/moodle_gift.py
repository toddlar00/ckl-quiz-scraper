"""Moodle GIFT format export.

GIFT format reference:
  ::Title:: Question text {
    =Correct answer#Feedback for correct
    ~Wrong answer 1#Feedback for wrong 1
    ~Wrong answer 2#Feedback for wrong 2
    ~Wrong answer 3#Feedback for wrong 3
  }

Special characters (= ~ # { } :) must be escaped with backslash in text.

Supports multiple question types:
  - Multiple Choice: standard {=correct ~wrong} format
  - True/False: {TRUE} or {FALSE}
  - Essay: {} (empty braces, Moodle auto-detects as essay)
  - Short Answer: {=answer} (single correct answer)
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _escape_gift(text):
    """Escape special GIFT characters."""
    for ch in ("\\", "~", "=", "#", "{", "}", ":"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", "\\n")


def export_moodle_gift(practice_sets, output_dir="output"):
    """Export to Moodle GIFT format (.gift file).

    In Moodle: Question bank -> Import -> GIFT format -> upload this file.
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

                    qtype = (q.question_type or "").lower()

                    # Essay questions: empty answer block
                    if "essay" in qtype:
                        f.write(f"::{title}::{q_text} {{}}\n\n")
                        continue

                    # Short answer questions: single correct answer
                    if "short answer" in qtype:
                        f.write(f"::{title}::{q_text} {{")
                        if q.correct_answer:
                            f.write(f"={_escape_gift(q.correct_answer)}")
                            if explanation:
                                f.write(f"#{explanation}")
                        f.write("}\n\n")
                        continue

                    # True/False questions
                    if "true/false" in qtype or "true or false" in qtype:
                        correct = q.correct_answer.upper() if q.correct_answer else ""
                        if correct in ("A", "TRUE", "T"):
                            tf = "TRUE"
                        elif correct in ("B", "FALSE", "F"):
                            tf = "FALSE"
                        else:
                            # Fall through to MC format if can't determine T/F
                            tf = None

                        if tf:
                            f.write(f"::{title}::{q_text} {{{tf}")
                            if explanation:
                                f.write(f"#{explanation}")
                            f.write("}\n\n")
                            continue

                    # Multiple Choice (default)
                    f.write(f"::{title}::{q_text} {{\n")

                    for choice in q.choices:
                        c_text = _escape_gift(choice["text"])
                        is_correct = choice.get("is_correct", False)
                        prefix = "=" if is_correct else "~"

                        # Use per-choice explanation if available, fall back to general
                        choice_expl = choice.get("explanation", "")
                        if choice_expl:
                            fb = _escape_gift(choice_expl)
                        elif explanation:
                            fb = explanation
                        else:
                            fb = ""

                        if fb:
                            f.write(f"  {prefix}{c_text}#{fb}\n")
                        else:
                            f.write(f"  {prefix}{c_text}\n")

                    f.write("}\n\n")

    logger.info("Exported Moodle GIFT: %s", filepath)
    return filepath
