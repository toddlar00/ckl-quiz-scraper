"""Canvas LMS QTI 1.2 export.

Produces a .zip file containing imsmanifest.xml and a quiz XML file
following the IMS QTI 1.2 specification for import into Canvas LMS.

Canvas import path: Course Settings → Import Course Content → QTI .zip file.
"""

import logging
import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

logger = logging.getLogger(__name__)


def _sanitize_ident(text):
    """Create a valid XML identifier from text."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', text)[:50]


def _pretty_xml(element):
    """Convert an ElementTree element to pretty-printed XML string."""
    raw = tostring(element, encoding="unicode")
    # Fix CDATA that got escaped by ElementTree
    raw = raw.replace("&lt;![CDATA[", "<![CDATA[")
    raw = raw.replace("]]&gt;", "]]>")
    try:
        dom = parseString(raw)
        return dom.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")
    except Exception:
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + raw


def _build_manifest(assessment_title, quiz_filename):
    """Build the imsmanifest.xml content."""
    manifest = Element("manifest", {
        "identifier": "manifest01",
        "xmlns": "http://www.imsglobal.org/xsd/imscp_v1p1",
    })
    SubElement(manifest, "organizations")
    resources = SubElement(manifest, "resources")
    resource = SubElement(resources, "resource", {
        "identifier": "res01",
        "type": "imsqti_xmlv1p2",
        "href": quiz_filename,
    })
    SubElement(resource, "file", href=quiz_filename)
    return _pretty_xml(manifest)


def _build_quiz_xml(practice_sets):
    """Build the QTI 1.2 quiz XML with all questions."""
    root = Element("questestinterop", {
        "xmlns": "http://www.imsglobal.org/xsd/ims_qtiasiv1p2",
    })

    question_id = 0
    for ps in practice_sets:
        assessment = SubElement(root, "assessment", {
            "title": ps.title,
            "ident": f"A_{_sanitize_ident(ps.title)}",
        })

        for ch in ps.chapters:
            section = SubElement(assessment, "section", {
                "title": ch.chapter_name,
                "ident": f"S_{_sanitize_ident(ch.chapter_name)}",
            })

            for q in ch.questions:
                question_id += 1
                _add_question_item(section, q, question_id)

    return _pretty_xml(root)


def _add_question_item(section, q, question_id):
    """Add a single multiple-choice question item to a QTI section."""
    q_ident = f"Q{question_id:04d}"
    rl_ident = f"RL{question_id:04d}"

    item = SubElement(section, "item", {
        "title": f"Question {question_id}",
        "ident": q_ident,
    })

    # Presentation block
    presentation = SubElement(item, "presentation")
    material = SubElement(presentation, "material")
    mattext = SubElement(material, "mattext", texttype="text/html")
    mattext.text = f"<![CDATA[<p>{q.question_text}</p>]]>"

    response_lid = SubElement(presentation, "response_lid", {
        "ident": rl_ident,
        "rcardinality": "Single",
    })
    render_choice = SubElement(response_lid, "render_choice", shuffle="No")

    # Add answer choices
    correct_ident = None
    for choice in q.choices:
        label_ident = choice["label"]
        resp_label = SubElement(render_choice, "response_label", ident=label_ident)
        mat = SubElement(resp_label, "material")
        mt = SubElement(mat, "mattext")
        mt.text = choice["text"]

        if choice.get("is_correct"):
            correct_ident = label_ident

    # Response processing
    resprocessing = SubElement(item, "resprocessing")
    outcomes = SubElement(resprocessing, "outcomes")
    SubElement(outcomes, "decvar", {
        "vartype": "Decimal",
        "defaultval": "0",
        "varname": "que_score",
    })

    if correct_ident:
        # Correct answer condition
        correct_cond = SubElement(resprocessing, "respcondition")
        condvar = SubElement(correct_cond, "conditionvar")
        varequal = SubElement(condvar, "varequal", respident=rl_ident)
        varequal.text = correct_ident
        setvar = SubElement(correct_cond, "setvar", {
            "varname": "que_score",
            "action": "Set",
        })
        setvar.text = "100"
        SubElement(correct_cond, "displayfeedback", {
            "feedbacktype": "Response",
            "linkrefid": f"{q_ident}_correct_fb",
        })

        # Incorrect answer condition
        incorrect_cond = SubElement(resprocessing, "respcondition")
        condvar2 = SubElement(incorrect_cond, "conditionvar")
        not_el = SubElement(condvar2, "not")
        varequal2 = SubElement(not_el, "varequal", respident=rl_ident)
        varequal2.text = correct_ident
        setvar2 = SubElement(incorrect_cond, "setvar", {
            "varname": "que_score",
            "action": "Set",
        })
        setvar2.text = "0"
        SubElement(incorrect_cond, "displayfeedback", {
            "feedbacktype": "Response",
            "linkrefid": f"{q_ident}_incorrect_fb",
        })

    # Per-choice feedback blocks
    for choice in q.choices:
        choice_expl = choice.get("explanation", "")
        if choice_expl:
            choice_fb = SubElement(item, "itemfeedback", ident=f"{q_ident}_{choice['label']}_fb")
            flow_mat_c = SubElement(choice_fb, "flow_mat")
            mat_c = SubElement(flow_mat_c, "material")
            mt_c = SubElement(mat_c, "mattext", texttype="text/html")
            mt_c.text = f"<![CDATA[<p>{choice_expl}</p>]]>"

    # General correct/incorrect feedback blocks
    if q.explanation:
        correct_fb = SubElement(item, "itemfeedback", ident=f"{q_ident}_correct_fb")
        flow_mat = SubElement(correct_fb, "flow_mat")
        mat = SubElement(flow_mat, "material")
        mt = SubElement(mat, "mattext", texttype="text/html")
        mt.text = f"<![CDATA[<p>Correct! {q.explanation}</p>]]>"

        incorrect_fb = SubElement(item, "itemfeedback", ident=f"{q_ident}_incorrect_fb")
        flow_mat2 = SubElement(incorrect_fb, "flow_mat")
        mat2 = SubElement(flow_mat2, "material")
        mt2 = SubElement(mat2, "mattext", texttype="text/html")
        correct_text = q.correct_answer or "unknown"
        mt2.text = f"<![CDATA[<p>Incorrect. The correct answer is {correct_text}. {q.explanation}</p>]]>"


def export_canvas_qti(practice_sets, output_dir="output"):
    """Export to Canvas QTI 1.2 ZIP package.

    In Canvas: Course Settings → Import Course Content → QTI .zip file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "quizzes_canvas_qti.zip")

    quiz_filename = "quiz_questions.xml"
    manifest_xml = _build_manifest("CKL Quiz Export", quiz_filename)
    quiz_xml = _build_quiz_xml(practice_sets)

    with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr(quiz_filename, quiz_xml)

    logger.info("Exported Canvas QTI: %s", filepath)
    return filepath
