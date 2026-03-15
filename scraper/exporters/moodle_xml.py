"""Moodle XML format export.

Moodle XML is the native rich quiz format for Moodle LMS.
It supports categories, feedback per answer, and general feedback.
"""

import logging
import os
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

logger = logging.getLogger(__name__)


def export_moodle_xml(practice_sets, output_dir="output"):
    """Export to Moodle XML format.

    In Moodle: Question bank → Import → Moodle XML format → upload.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_moodle.xml")

    quiz = Element("quiz")

    question_id = 0
    for ps in practice_sets:
        for ch in ps.chapters:
            # Add category question
            cat_q = SubElement(quiz, "question", type="category")
            cat_el = SubElement(cat_q, "category")
            cat_text = SubElement(cat_el, "text")
            cat_text.text = f"CKL/{ps.title}/{ch.chapter_name}"

            for q in ch.questions:
                question_id += 1
                mc = SubElement(quiz, "question", type="multichoice")

                # Question name
                name = SubElement(mc, "name")
                name_text = SubElement(name, "text")
                name_text.text = f"CKL Q{question_id}"

                # Question text
                qtext = SubElement(mc, "questiontext", format="html")
                qtext_text = SubElement(qtext, "text")
                qtext_text.text = f"<![CDATA[<p>{q.question_text}</p>]]>"

                # General feedback (explanation)
                if q.explanation:
                    gf = SubElement(mc, "generalfeedback", format="html")
                    gf_text = SubElement(gf, "text")
                    gf_text.text = f"<![CDATA[<p>{q.explanation}</p>]]>"

                # Settings
                SubElement(mc, "defaultgrade").text = "1.0000000"
                SubElement(mc, "penalty").text = "0.3333333"
                SubElement(mc, "hidden").text = "0"
                SubElement(mc, "single").text = "true"
                SubElement(mc, "shuffleanswers").text = "true"
                SubElement(mc, "answernumbering").text = "abc"

                # Answer choices
                for choice in q.choices:
                    fraction = "100" if choice.get("is_correct") else "0"
                    answer = SubElement(mc, "answer", fraction=fraction, format="html")
                    a_text = SubElement(answer, "text")
                    a_text.text = f"<![CDATA[<p>{choice['text']}</p>]]>"

                    # Per-answer feedback
                    fb = SubElement(answer, "feedback", format="html")
                    fb_text = SubElement(fb, "text")
                    if choice.get("is_correct") and q.explanation:
                        fb_text.text = f"<![CDATA[<p>Correct! {q.explanation}</p>]]>"
                    elif not choice.get("is_correct") and q.correct_answer:
                        fb_text.text = f"<![CDATA[<p>Incorrect. The correct answer is {q.correct_answer}.</p>]]>"

    # Pretty print
    raw = tostring(quiz, encoding="unicode")
    # Fix CDATA sections that got escaped
    raw = raw.replace("&lt;![CDATA[", "<![CDATA[")
    raw = raw.replace("]]&gt;", "]]>")

    pretty = '<?xml version="1.0" encoding="UTF-8"?>\n' + raw

    try:
        dom = parseString(pretty)
        pretty = dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    except Exception:
        pass  # Fall back to non-pretty output

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(pretty)

    logger.info("Exported Moodle XML: %s", filepath)
    return filepath
