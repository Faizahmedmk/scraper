"""
Weekly job: scrape Clutch, then PUSH the reviews to an n8n webhook.
n8n writes them into Google Sheets. Schedule this file with Windows Task Scheduler.

  python run_weekly.py              full run: scrape + send
  python run_weekly.py --send-only  skip scraping, send what is already in output/all_reviews.csv
"""
import argparse, hashlib, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # so Task Scheduler finds ./output
import pandas as pd
import scraper

# ===================== EDIT THESE =====================
WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "https://n8n.moveneticsdigital.com/webhook-test/clutch-reviews")
API_KEY = os.environ.get("N8N_API_KEY", "Im884BR8DfzVR0UvIW8ElZEU")    # must match the n8n 'Valid token?' node
CATEGORY = "https://clutch.co/developers"
MAX_COMPANIES = 7
MAX_DIR_PAGES = 1
MIN_RATING, MAX_RATING = 1, 3
# ======================================================

LOG_FILE = os.path.join(scraper.OUT_DIR, "weekly_log.txt")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    os.makedirs(scraper.OUT_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def post(payload):
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, 4):
        req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "x-api-key": API_KEY})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                log(f"n8n answered HTTP {r.status}")
                return True
        except urllib.error.HTTPError as e:
            log(f"n8n returned HTTP {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            log(f"Could not reach n8n: {e}")
        time.sleep(10 * attempt)
    return False


def build_rows():
    df = pd.read_csv(scraper.RAW_CSV)
    df = df.drop_duplicates(subset=["company_url", "review_title", "reviewer_name", "review_date"])
    df = df[df["rating"].between(MIN_RATING, MAX_RATING)].fillna("").copy()
    df.insert(0, "review_id", [hashlib.md5("|".join(str(x) for x in (r.company_url, r.review_title, r.reviewer_name, r.review_date)).encode()).hexdigest()[:12]
                               for r in df.itertuples()])
    df["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return json.loads(df.to_json(orient="records"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-only", action="store_true")
    a = ap.parse_args()
    if "PASTE_YOUR" in WEBHOOK_URL:
        sys.exit("Set WEBHOOK_URL at the top of run_weekly.py (or the N8N_WEBHOOK_URL environment variable).")

    if not a.send_only:
        log(f"Weekly run started: {CATEGORY}, {MAX_COMPANIES} companies, rating {MIN_RATING}-{MAX_RATING}")
        if os.path.exists(scraper.RAW_CSV):      # start clean so only this run's companies are sent
            os.replace(scraper.RAW_CSV, os.path.join(scraper.OUT_DIR, "all_reviews_previous.csv"))
        state = {}
        try:
            scraper.run_scrape(CATEGORY, MAX_COMPANIES, MAX_DIR_PAGES, (2, 4),
                               log=log, state=state, resume=False)
        except BaseException as e:               # includes SystemExit (e.g. Chrome not found)
            log(f"Scrape crashed: {e}")
            post({"status": "failed", "message": f"Scrape crashed: {e}", "count": 0, "rows": []})
            sys.exit(1)
        if state.get("failed", 0) > 0 or not os.path.exists(scraper.RAW_CSV):
            msg = f"{state.get('failed', 0)} company(ies) failed (verification page not solved?)"
            log(msg)
            post({"status": "failed", "message": msg, "count": 0, "rows": []})
            sys.exit(1)

    rows = build_rows()
    log(f"Sending {len(rows)} reviews to n8n...")
    ok = post({"status": "ok", "message": "", "category": CATEGORY, "count": len(rows), "rows": rows})
    log("Done." if ok else "FAILED to deliver to n8n.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
