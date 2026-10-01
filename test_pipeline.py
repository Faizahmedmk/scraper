"""Simulates what n8n does: start a refresh scrape, wait for it, fetch the reviews."""
import csv, json, sys, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:5000"
CATEGORY = "https://clutch.co/developers"
MAX_COMPANIES = 2
MIN_RATING, MAX_RATING = 5, 5


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {path}: {e.read().decode()[:200]}")
    except urllib.error.URLError:
        sys.exit("Cannot reach the scraper service. Is 'python app.py' running?")


print("1) Checking the service...")
print("   status:", call("GET", "/api/status")["state"])

print("2) Starting a scrape (refresh mode, like n8n)...")
call("POST", "/api/start", {"category": CATEGORY, "max_companies": MAX_COMPANIES,
                            "max_dir_pages": 1, "refresh": True})

print("3) Waiting for it to finish (checks every 10 seconds)...")
while True:
    time.sleep(10)
    s = call("GET", "/api/status")
    last = s["log"][-1] if s["log"] else ""
    print(f"   {s['state']:9} companies {s['done']}/{s['total']}  failed={s['failed']}  | {last}")
    if s["state"] not in ("starting", "running"):
        break

if s["state"] != "finished" or s["failed"] != 0:
    sys.exit(f"4) NOT OK: state={s['state']} failed={s['failed']}. n8n would send the failure alert.")
print("4) Run finished with no failures.")

print("5) Fetching reviews like n8n does...")
r = call("GET", f"/api/reviews?min={MIN_RATING}&max={MAX_RATING}")
print(f"   {r['count']} reviews between {MIN_RATING} and {MAX_RATING}")
if not r["rows"]:
    sys.exit("   No rows returned. n8n would not touch the sheet.")
row = r["rows"][0]
print("   first row:", row["review_id"], "|", row["company"], "|", row["rating"], "|", row["review_title"])

cols = list(r["rows"][0].keys())
with open("output/n8n_test_rows.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(r["rows"])
print("6) Saved output/n8n_test_rows.csv  (this is exactly what would go into Google Sheets)")
print("DONE - the pipeline works end to end.")
