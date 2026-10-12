"""
Weekly job: scrape Clutch with local Chrome, then PUSH the leads to the cPanel app,
which stores them in MariaDB. Schedule this file with Windows Task Scheduler / cron.

  python run_weekly.py              full run: scrape + send
  python run_weekly.py --send-only  skip scraping, send what is already in output/all_reviews.csv

Settings (environment variables or .env, see .env.example):
  INGEST_URL       https://<your-subdomain>/api/ingest
  INGEST_API_KEY   must match INGEST_API_KEY on the server
"""
import argparse, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # so schedulers find ./output
import config
import scraper

INGEST_URL = os.environ.get("INGEST_URL", "")
API_KEY = config.INGEST_API_KEY
CATEGORY = os.environ.get("CLUTCH_CATEGORY", "https://clutch.co/developers")
MAX_COMPANIES = int(os.environ.get("CLUTCH_MAX_COMPANIES", "7"))
MAX_DIR_PAGES = int(os.environ.get("CLUTCH_MAX_DIR_PAGES", "1"))
BATCH = 500

LOG_FILE = os.path.join(scraper.OUT_DIR, "weekly_log.txt")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    os.makedirs(scraper.OUT_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def post(rows):
    data = json.dumps({"rows": rows}).encode("utf-8")
    for attempt in range(1, 4):
        req = urllib.request.Request(INGEST_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "x-api-key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                log(f"Server answered HTTP {r.status}: {r.read().decode()[:100]}")
                return True
        except urllib.error.HTTPError as e:
            log(f"Server returned HTTP {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            log(f"Could not reach server: {e}")
        time.sleep(10 * attempt)
    return False


def send(rows):
    for i in range(0, len(rows), BATCH):
        if not post(rows[i:i + BATCH]):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-only", action="store_true")
    a = ap.parse_args()
    if not INGEST_URL or not API_KEY:
        sys.exit("Set INGEST_URL and INGEST_API_KEY (environment variables or .env).")

    if a.send_only:
        rows = scraper.read_raw()
        log(f"Sending {len(rows)} saved reviews...")
        ok = send(rows)
    else:
        log(f"Run started: {CATEGORY}, {MAX_COMPANIES} companies")
        state, ok = {}, True

        def save(rows):
            nonlocal ok
            scraper.append_raw(rows)         # local backup
            ok = send(rows) and ok

        try:
            scraper.run_scrape(CATEGORY, MAX_COMPANIES, MAX_DIR_PAGES, (2, 4),
                               log=log, state=state, resume=False, save=save)
        except BaseException as e:           # includes SystemExit (e.g. Chrome not found)
            log(f"Scrape crashed: {e}")
            sys.exit(1)
        if state.get("failed", 0) > 0:
            log(f"{state['failed']} company(ies) failed (verification page not solved?)")
            ok = False
    log("Done." if ok else "FINISHED WITH ERRORS.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
