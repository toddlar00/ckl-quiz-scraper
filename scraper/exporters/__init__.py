"""Quiz data exporters for various formats."""

from scraper.exporters.anki import export_anki
from scraper.exporters.canvas_qti import export_canvas_qti
from scraper.exporters.csv_export import export_csv
from scraper.exporters.json_export import export_json
from scraper.exporters.kahoot import export_kahoot
from scraper.exporters.moodle_gift import export_moodle_gift
from scraper.exporters.moodle_xml import export_moodle_xml
from scraper.exporters.quizlet import export_quizlet

EXPORTERS = {
    "json": export_json,
    "csv": export_csv,
    "anki": export_anki,
    "quizlet": export_quizlet,
    "kahoot": export_kahoot,
    "moodle_gift": export_moodle_gift,
    "moodle_xml": export_moodle_xml,
    "canvas_qti": export_canvas_qti,
}

ALL_FORMATS = list(EXPORTERS.keys())


def export_all(practice_sets, output_dir="output", formats=None):
    """Export practice sets to the specified formats.

    Args:
        practice_sets: List of PracticeSet objects.
        output_dir: Output directory path.
        formats: List of format names, or None for all formats.

    Returns:
        Dict mapping format name to output file path.
    """
    if formats is None:
        formats = ALL_FORMATS

    results = {}
    for fmt in formats:
        if fmt in EXPORTERS:
            results[fmt] = EXPORTERS[fmt](practice_sets, output_dir)

    return results
