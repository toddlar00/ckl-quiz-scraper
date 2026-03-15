# CKL Quiz Scraper

A Python + Selenium scraper that logs into [Core Knowledge for Lawyers](https://coreknowledgeforlawyers.com), discovers practice sets and chapters, and extracts quiz questions with answer choices, correct answers, and explanations.

Exports to **8 formats**: JSON, CSV, Anki, Quizlet, Kahoot, Moodle GIFT, Moodle XML, and Canvas QTI.

## Setup

```bash
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your CKL email and password
```

### .env Configuration

| Variable | Description | Default |
|---|---|---|
| `CKL_USERNAME` | Your CKL email | (required) |
| `CKL_PASSWORD` | Your CKL password | (required) |
| `CKL_BASE_URL` | Site base URL | `https://coreknowledgeforlawyers.com` |
| `CKL_HEADLESS` | Run browser headless | `true` |
| `CKL_PAGE_LOAD_TIMEOUT` | Page load timeout (sec) | `30` |
| `CKL_IMPLICIT_WAIT` | Implicit wait (sec) | `10` |
| `CKL_REQUEST_DELAY` | Delay between questions (sec) | `1.0` |

## Usage

```bash
# Scrape everything, export to all formats
python main.py

# Scrape one practice set
python main.py --practice-set "Civil Procedure"

# Scrape one chapter
python main.py --practice-set "Civil Procedure" --chapter "Subject Matter"

# Scrape a specific chapter URL directly
python main.py --chapter-url "https://coreknowledgeforlawyers.com/..."

# Export only specific formats
python main.py --format json anki moodle_gift canvas_qti

# Debug mode (visible browser + verbose logging)
python main.py --no-headless -v

# Re-scrape everything (ignore saved progress)
python main.py --fresh

# Custom output directory
python main.py -o my_results

# Preview what would be scraped without actually scraping
python main.py --dry-run

# Save log output to a file
python main.py --log-file scrape.log
```

### CLI Options

| Flag | Description |
|---|---|
| `--practice-set TEXT` | Filter practice sets by name substring |
| `--chapter TEXT` | Filter chapters by name substring |
| `--chapter-url URL` | Scrape a specific chapter URL directly |
| `--format FMT [FMT ...]` | Export formats (default: all) |
| `--output-dir, -o DIR` | Output directory (default: `output/`) |
| `--no-headless` | Show the browser window |
| `--skip-login` | Skip login (use saved cookies) |
| `--fresh` | Ignore saved progress, re-scrape everything |
| `--site NAME` | Quiz site to scrape (default: `ckl`) |
| `--delay SECONDS` | Fixed delay between questions (disables adaptive) |
| `--verbose, -v` | Debug-level logging |
| `--dry-run` | Discover structure without scraping questions |
| `--log-file PATH` | Also write log output to a file |

## Export Formats

| Format | File | Import Into |
|---|---|---|
| **JSON** | `quizzes.json` | Any app, custom processing |
| **CSV** | `quizzes.csv` | Excel, Google Sheets, databases |
| **Anki** | `quizzes_anki.txt` | Anki → File → Import (TSV, HTML) |
| **Quizlet** | `quizzes_quizlet.txt` | Quizlet → Create Set → Import |
| **Kahoot** | `quizzes_kahoot.csv` | Kahoot → Create → Import Spreadsheet |
| **Moodle GIFT** | `quizzes_moodle.gift` | Moodle → Question Bank → Import → GIFT |
| **Moodle XML** | `quizzes_moodle.xml` | Moodle → Question Bank → Import → Moodle XML |
| **Canvas QTI** | `quizzes_canvas_qti.zip` | Canvas → Import Content → QTI .zip |

### JSON Structure

```json
[
  {
    "practice_set": "Civil Procedure: Cases, Materials, and Questions",
    "chapters": [
      {
        "chapter": "Chapter 2: Subject Matter Jurisdiction",
        "questions": [
          {
            "number": 1,
            "type": "Multiple Choice",
            "question": "P enters into a contract with D...",
            "choices": [
              {"label": "A", "text": "P's case...", "is_correct": false},
              {"label": "B", "text": "P's case...", "is_correct": false},
              {"label": "C", "text": "P's case...", "is_correct": true},
              {"label": "D", "text": "P's case...", "is_correct": false}
            ],
            "correct_answer": "C",
            "explanation": "P's case against D does not invoke..."
          }
        ]
      }
    ]
  }
]
```

## Features

### Resume Support
Progress is automatically saved after each chapter. If the scraper is interrupted (Ctrl+C, crash, etc.), re-run the same command and it will skip already-scraped chapters. Use `--fresh` to start over.

### Cookie Persistence
After a successful login, cookies are saved to `.ckl_cookies.json`. On the next run, the scraper tries these cookies first to avoid re-entering credentials. Delete the file to force a fresh login.

### Dry Run Mode
Use `--dry-run` to discover and list all practice sets and chapters without actually scraping any questions. Useful for previewing scope before a long scrape.

### Log to File
Use `--log-file scrape.log` to save all log output to a file in addition to the console. Useful for reviewing scrape history or debugging issues after the fact.

### Summary Statistics
After scraping completes, a detailed summary is printed including question counts per practice set, question type breakdown, explanation coverage, average time per question, and exported file sizes.

### Automatic Diagnostics
When something goes wrong (login failure, missing elements, parse errors), the scraper automatically captures:
- **Screenshots** → `debug_screenshots/*.png`
- **Page HTML source** → `debug_screenshots/*.html`

These files help diagnose issues without needing `--no-headless`.

### Adaptive Rate Limiting
The scraper uses an adaptive delay system that automatically finds the fastest safe scraping speed. It starts with a 9-second budget spread across 5 sleep points per question cycle. On each successful scrape, the budget decreases by 1 second; on failure, it increases by 1 second. The budget is clamped between 0.5 and 30 seconds and persists across runs in `.ckl_adaptive_delay.json`. Use `--delay` to override with a fixed delay, or `--fresh` to reset the adaptive state.

## Testing

Run the test suite with pytest:

```bash
pytest tests/ -v
```

Tests cover all 8 export formats, adaptive delay behavior, and the site plugin system (70 tests total).

## Project Structure

```
ckl-quiz-scraper/
├── main.py                          # CLI entry point
├── scraper/
│   ├── config.py                    # Environment / settings
│   ├── browser.py                   # WebDriver, login, diagnostics, cookies
│   ├── quiz_scraper.py              # Adaptive delay, progress tracking, helpers
│   ├── base.py                      # BaseScraper ABC (plugin interface)
│   ├── sites/
│   │   ├── __init__.py              # Site plugin registry
│   │   ├── ckl.py                   # CKL site implementation
│   │   └── example_site.py          # Template for adding new sites
│   └── exporters/
│       ├── __init__.py              # Export dispatcher
│       ├── json_export.py           # JSON
│       ├── csv_export.py            # CSV
│       ├── anki.py                  # Anki TSV
│       ├── quizlet.py               # Quizlet TSV
│       ├── kahoot.py                # Kahoot spreadsheet
│       ├── moodle_gift.py           # Moodle GIFT
│       ├── moodle_xml.py            # Moodle XML
│       └── canvas_qti.py            # Canvas QTI 1.2
├── tests/
│   ├── conftest.py                  # Shared test fixtures
│   ├── test_exporters.py            # Exporter tests (42 tests)
│   ├── test_adaptive_delay.py       # Adaptive delay tests (15 tests)
│   └── test_sites.py                # Site plugin tests (13 tests)
├── output/                          # Exported files (gitignored)
├── debug_screenshots/               # Error diagnostics (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Adding a New Quiz Site

The scraper uses a plugin architecture. To add support for a new quiz website:

1. Copy `scraper/sites/example_site.py` to a new file (e.g., `my_site.py`)
2. Implement all abstract methods from `BaseScraper` for the target site's HTML structure
3. Register in `scraper/sites/__init__.py`:
   ```python
   from scraper.sites.my_site import MySiteScraper
   SITE_SCRAPERS["my_site"] = MySiteScraper
   ```
4. Run: `python main.py --site my_site`

The framework handles browser management, adaptive delays, progress tracking, resume support, and export to all 8 formats. Your plugin only needs to implement site-specific DOM interaction.

## Troubleshooting

| Problem | Solution |
|---|---|
| Login fails | Check `.env` credentials. Run with `--no-headless` to watch. Check `debug_screenshots/`. |
| No practice sets found | Verify your account has practice sets. Check `debug_screenshots/`. |
| No questions scraped | Use `--fresh` to re-scrape. Check `debug_screenshots/` for page state. |
| Chrome not found | Install Chrome or Chromium. `webdriver-manager` handles chromedriver. |
| Scraper interrupted | Just re-run — it resumes from saved progress automatically. |
| Rate limited by site | Increase `--delay` (e.g., `--delay 3`). |
| Stale export data | Delete `.ckl_progress.json` or use `--fresh`. |
| Canvas import fails | Canvas fails silently on invalid QTI. Check zip contents. |
