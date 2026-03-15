# CKL Quiz Scraper

A Python + Selenium scraper that logs into [Core Knowledge for Lawyers](https://coreknowledgeforlawyers.com), discovers quiz pages, and extracts questions, answer choices, correct answers, and explanations. Exports to both JSON and CSV.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env with your login credentials
```

### .env Configuration

| Variable | Description | Default |
|---|---|---|
| `CKL_USERNAME` | Your login username/email | (required) |
| `CKL_PASSWORD` | Your login password | (required) |
| `CKL_BASE_URL` | Base URL of the site | `https://coreknowledgeforlawyers.com` |
| `CKL_HEADLESS` | Run browser headless | `true` |
| `CKL_PAGE_LOAD_TIMEOUT` | Page load timeout (seconds) | `30` |
| `CKL_IMPLICIT_WAIT` | Implicit wait timeout (seconds) | `10` |

## Usage

```bash
# Auto-discover and scrape all quizzes
python main.py

# Scrape a specific quiz URL
python main.py --url "https://coreknowledgeforlawyers.com/quiz/example"

# Run with visible browser for debugging
python main.py --no-headless

# Custom output directory
python main.py -o my_results

# Verbose logging
python main.py -v
```

## Output

Results are saved to the `output/` directory (or custom directory via `-o`):

- **quizzes.json** - Structured JSON with all quiz data
- **quizzes.csv** - Flat CSV with one row per question

### JSON Structure

```json
[
  {
    "title": "Quiz Title",
    "url": "https://...",
    "question_count": 10,
    "questions": [
      {
        "number": 1,
        "question": "What is...?",
        "choices": [
          {"label": "A", "text": "Option 1", "is_correct": false},
          {"label": "B", "text": "Option 2", "is_correct": true}
        ],
        "correct_answer": "B. Option 2",
        "explanation": "Because...",
        "source_url": "https://..."
      }
    ]
  }
]
```

## Project Structure

```
ckl-quiz-scraper/
├── main.py                 # CLI entry point
├── scraper/
│   ├── __init__.py
│   ├── config.py           # Environment/settings
│   ├── browser.py          # WebDriver setup and login
│   ├── quiz_scraper.py     # Quiz discovery and scraping
│   └── exporter.py         # JSON/CSV export
├── output/                 # Generated output (gitignored)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Customization

The scraper uses multiple strategies to find quiz content:

1. **Login detection** - Tries common login page patterns (WordPress, LMS, custom)
2. **Quiz discovery** - Crawls common paths (`/quizzes`, `/courses`, etc.) and follows links containing quiz keywords
3. **Question extraction** - Looks for structured quiz containers (CSS classes like `.question`, `.quiz-question`) and falls back to regex text parsing
4. **Answer detection** - Identifies correct answers via CSS classes, data attributes, and visual indicators

If the site uses a non-standard structure, provide specific quiz URLs with `--url` and adjust the CSS selectors in `scraper/quiz_scraper.py`.
