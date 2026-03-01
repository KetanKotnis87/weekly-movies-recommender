# Weekly Movie & Web Series Recommender

An automated Python service that fetches trending movies and web series from TMDB, scores them using IMDB ratings and popularity data, and emails a curated PDF report every Saturday morning. The report covers Hindi, English, and Kannada content across Action, Thriller, Drama, and Comedy genres, with Indian OTT platform availability included for each title.

---

## Prerequisites

- Python 3.10 or later
- A free [TMDB API key](https://www.themoviedb.org/settings/api)
- A free [OMDb API key](https://www.omdbapi.com/apikey.aspx)
- A Gmail account with [App Password](https://myaccount.google.com/apppasswords) enabled (requires 2-Step Verification)

---

## Local Setup

```bash
# 1. Clone the repository
git clone <repo-url>
cd weekly-movies-recommender

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy the example env file and fill in your credentials
cp .env.example .env
# Edit .env with your actual API keys and email credentials

# 4. Run a dry-run (generates PDF, skips email)
python src/main.py --dry-run

# 5. Force a full run on a non-Saturday (generates PDF AND sends email)
python src/main.py --dry-run --force
```

The generated PDF is saved to `output/movie_recommendations_YYYY-MM-DD.pdf`.
Execution logs are written to `logs/run_YYYY-MM-DD.log` (last 8 runs are retained).

---

## CLI Flags

| Flag | Description |
|---|---|
| `--dry-run` | Run the full pipeline and save the PDF locally, but skip email delivery. |
| `--force` | Bypass the Saturday gate — run on any day (useful for testing). |

---

## PythonAnywhere Deployment (Free Tier)

### Step 1 — Upload files

In your PythonAnywhere dashboard, open a Bash console and run:

```bash
git clone <repo-url> ~/weekly-movies-recommender
```

Or upload the files manually via the **Files** tab.

### Step 2 — Install dependencies

```bash
cd ~/weekly-movies-recommender
pip3.10 install --user -r requirements.txt
```

### Step 3 — Set environment variables

Create `~/weekly-movies-recommender/.env` with your credentials:

```bash
cp ~/weekly-movies-recommender/.env.example ~/weekly-movies-recommender/.env
nano ~/weekly-movies-recommender/.env
# Fill in TMDB_API_KEY, OMDB_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL
```

### Step 4 — Create a scheduled task

1. Go to the **Tasks** tab in your PythonAnywhere dashboard.
2. Click **Add a new scheduled task**.
3. Set the time to **02:30 UTC** (= 08:00 IST, within the 07:00–09:00 IST window).
4. Set the command to:
   ```
   /usr/bin/python3.10 /home/<your-username>/weekly-movies-recommender/src/main.py
   ```
5. Save the task.

The service will run daily at 08:00 IST. The Saturday gate inside `main.py` ensures the pipeline only executes on Saturdays; on all other days it exits immediately with code 0 (no API calls, no email).

### Step 5 — Verify

Check `~/weekly-movies-recommender/logs/` after the first Saturday run to confirm success.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `TMDB_API_KEY` | Yes | TMDB v3 API key. Get yours free at [themoviedb.org](https://www.themoviedb.org/settings/api). |
| `OMDB_API_KEY` | Yes | OMDb API key. Free tier allows 1,000 requests/day. Get at [omdbapi.com](https://www.omdbapi.com/apikey.aspx). |
| `GMAIL_ADDRESS` | Yes | The Gmail address the report is sent from (e.g. `yourname@gmail.com`). |
| `GMAIL_APP_PASSWORD` | Yes | A 16-character Gmail App Password. Requires 2-Step Verification. See [Google's guide](https://support.google.com/accounts/answer/185833). |
| `RECIPIENT_EMAIL` | Yes | The email address that receives the weekly PDF report. |

---

## Scheduling Note

The PythonAnywhere free tier does not support persistent background processes. Instead, a **daily scheduled task** is used, and a **Saturday gate** is enforced in code:

```python
# In src/main.py
if datetime.today().weekday() != 5 and not force:
    sys.exit(0)   # Not Saturday — exit cleanly
```

- `weekday() == 5` corresponds to Saturday in Python's `datetime` module.
- The task fires daily at 08:00 IST; on non-Saturdays it exits in under one second without making any API calls.
- On Saturdays it runs the full pipeline: fetch → filter → score → generate PDF → send email.
- **Idempotency**: if the pipeline is triggered twice on the same Saturday, the second run detects a sentinel file and skips email delivery, preventing duplicate sends.

---

## Project Structure

```
weekly-movies-recommender/
├── src/
│   ├── __init__.py         # Empty package marker
│   ├── config.py           # All constants and Config dataclass
│   ├── data_fetcher.py     # TMDBClient + OMDbClient
│   ├── scorer.py           # ContentItem, filters, scoring, ranking
│   ├── pdf_generator.py    # ReportLab PDF report builder
│   ├── email_sender.py     # Gmail SMTP email delivery
│   └── main.py             # Orchestrator + CLI entry point
├── tests/                  # pytest test suite
├── docs/
│   ├── PRD.md
│   └── USE_CASES.md
├── logs/                   # Auto-created; retains last 8 run logs
├── output/                 # Auto-created; stores generated PDFs
├── .env.example            # Environment variable template
├── requirements.txt
└── README.md
```
