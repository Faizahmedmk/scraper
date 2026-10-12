# Clutch Lead Pipeline

Scrapes Clutch reviews and stores them as leads in MariaDB, with a small password-protected dashboard.

```
 your PC (Chrome)                         cPanel subdomain (Python app)
 run_weekly.py  --- POST /api/ingest --->  app.py  --->  MariaDB `leads` table
                                           dashboard: filter, CSV/Excel download
```

Clutch sits behind Cloudflare and needs a real, visible Chrome (sometimes a manual "verify you are human"
click). Shared cPanel hosting has no Chrome or display, so scraping runs on a machine with Chrome and
pushes the results to the cPanel app. The app itself is plain Flask + PyMySQL.

## Deploy to cPanel

1. **MariaDB**: cPanel > *MySQL Databases* > create a database and a user, give the user ALL privileges.
   The `leads` table is created automatically on first use.
2. **Upload** the contents of this folder (not `output/`, `.env`, `.git`) to e.g. `~/leads_app`.
3. cPanel > **Setup Python App** > Create:
   - Python version 3.9+, Application root `leads_app`, Application URL = your subdomain
   - Startup file `passenger_wsgi.py`, entry point `application`
4. Add **Environment variables** in that screen:

   | Name | Value |
   |---|---|
   | DB_HOST | `localhost` |
   | DB_NAME / DB_USER / DB_PASSWORD | the cPanel database credentials (names are prefixed with the cPanel user) |
   | APP_USER / APP_PASSWORD | dashboard login (APP_PASSWORD is required; the app refuses to serve without it) |
   | INGEST_API_KEY | long random string; the scraper must send the same value |

5. In the same screen: *Run Pip Install* with `requirements.txt`, then **Restart**.
6. Open the subdomain, log in, and check `/health`.

Optional: load the existing CSV into the database (run from the cPanel app terminal, or locally with DB env set):

    python db.py init
    python db.py import-csv output/all_reviews.csv

## Run the scraper (on a machine with Chrome)

    python -m venv venv && venv\Scripts\activate
    pip install -r requirements.txt -r requirements-scraper.txt
    copy .env.example .env      # set INGEST_URL and INGEST_API_KEY
    python run_weekly.py

Schedule `run_weekly.py` with Windows Task Scheduler (or cron). Other settings: `CLUTCH_CATEGORY`,
`CLUTCH_MAX_COMPANIES`, `CLUTCH_MAX_DIR_PAGES`. If Chrome is not found, set `CHROME_PATH`.

Local interactive use: `python app.py` (needs the DB env vars, `ENABLE_SCRAPER=1` to show the Start button).

## API

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/ingest` `{"rows":[...]}` | `x-api-key` header | upsert leads (deduplicated by review) |
| `GET /api/reviews?min=&max=` | dashboard login | leads in a rating range as JSON |
| `GET /download/csv\|xlsx?min=&max=` | dashboard login | export |
| `GET /health` | none | liveness |

## Files
- `passenger_wsgi.py` cPanel entry point
- `app.py` dashboard + API
- `db.py` MariaDB schema and queries
- `config.py` environment settings
- `scraper.py`, `clutch_parser.py` Chrome crawling and HTML parsing
- `run_weekly.py` scheduled scrape + push to the app
