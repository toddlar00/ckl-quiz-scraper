# CKL Quiz Scraper

A Python + Selenium scraper that logs into [Core Knowledge for Lawyers](https://coreknowledgeforlawyers.com), discovers practice sets and chapters, and extracts quiz questions with answer choices, correct answers, and explanations.

Exports to **7 formats**: JSON, CSV, Anki, Quizlet, Kahoot, Moodle GIFT, and Moodle XML.

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
python main.py --format json anki moodle_gift

# Debug mode (visible browser + verbose logging)
python main.py --no-headless -v

# Re-scrape everything (ignore saved progress)
python main.py --fresh

# Custom output directory
python main.py -o my_results
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
| `--delay SECONDS` | Delay between questions (default: 1.0) |
| `--verbose, -v` | Debug-level logging |

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

### Automatic Diagnostics
When something goes wrong (login failure, missing elements, parse errors), the scraper automatically captures:
- **Screenshots** → `debug_screenshots/*.png`
- **Page HTML source** → `debug_screenshots/*.html`

These files help diagnose issues without needing `--no-headless`.

### Rate Limiting
A configurable delay (default 1 second) is applied between questions to avoid overloading the server. Adjust with `--delay` or `CKL_REQUEST_DELAY`.

## Project Structure

```
ckl-quiz-scraper/
├── main.py                          # CLI entry point
├── scraper/
│   ├── config.py                    # Environment / settings
│   ├── browser.py                   # WebDriver, login, diagnostics, cookies
│   ├── quiz_scraper.py              # Discovery, scraping, progress tracking
│   └── exporters/
│       ├── __init__.py              # Export dispatcher
│       ├── json_export.py           # JSON
│       ├── csv_export.py            # CSV
│       ├── anki.py                  # Anki TSV
│       ├── quizlet.py               # Quizlet TSV
│       ├── kahoot.py                # Kahoot spreadsheet
│       ├── moodle_gift.py           # Moodle GIFT
│       └── moodle_xml.py            # Moodle XML
├── output/                          # Exported files (gitignored)
├── debug_screenshots/               # Error diagnostics (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

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
