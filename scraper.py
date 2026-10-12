"""
Clutch review scraper (Selenium).

Chrome is started as a normal browser process and Selenium attaches to it.
If Cloudflare shows a verification page, solve it once in that window; the
script waits, and the saved profile keeps you verified for later runs.

Usage:
  python scraper.py --category "https://clutch.co/developers" --min-rating 5 --max-rating 5
  python scraper.py --export-only --min-rating 4.5        # re-filter without scraping
"""
import argparse, csv, os, random, shutil, socket, subprocess, sys, time
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

from clutch_parser import COLUMNS, parse_company_links, parse_reviews

PORT = 9222
PROFILE_DIR = os.path.abspath("chrome_profile")
OUT_DIR = "output"
RAW_CSV = os.path.join(OUT_DIR, "all_reviews.csv")
DONE_TXT = os.path.join(OUT_DIR, "done_companies.txt")


# ---------------------------------------------------------------- browser
def chrome_path():
    """Path to Chrome, or None if it is not installed."""
    cands = [
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"), shutil.which("chrome"),
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def find_chrome():
    c = chrome_path()
    if not c:
        sys.exit("Chrome not found. Set the CHROME_PATH environment variable to chrome.exe.")
    return c


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    if not port_open(PORT):
        print("Starting Chrome...")
        subprocess.Popen([find_chrome(), f"--remote-debugging-port={PORT}",
                          f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
                          "--no-default-browser-check", "about:blank"])
        for _ in range(30):
            if port_open(PORT):
                break
            time.sleep(1)
        else:
            sys.exit("Chrome did not start.")
    opts = Options()
    opts.debugger_address = f"127.0.0.1:{PORT}"
    return webdriver.Chrome(options=opts)


def is_challenge(driver):
    t = (driver.title or "").lower()
    return any(k in t for k in ("just a moment", "security verification", "attention required"))


class Stopped(Exception):
    pass


def make_fetcher(driver, delay, stop=None, log=print):
    """Returns fetch(url) -> html. Waits for you if a Cloudflare check appears."""
    from selenium.webdriver.common.by import By

    def fetch(url, timeout=300):
        driver.get(url)
        start, warned = time.time(), False
        while time.time() - start < timeout:
            if stop is not None and stop.is_set():
                raise Stopped()
            if not is_challenge(driver) and driver.find_elements(By.CSS_SELECTOR, "h1"):
                time.sleep(random.uniform(*delay))
                return driver.page_source
            if not warned and is_challenge(driver):
                log("Verification page shown. Solve it in the Chrome window; waiting...")
                warned = True
            time.sleep(2)
        raise TimeoutError(f"Page never became ready: {url}")
    return fetch


# ---------------------------------------------------------------- crawling
def with_page(url, page):
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q["page"] = page
    return urlunparse(u._replace(query=urlencode(q)))


def collect_company_links(fetch, category, max_dir_pages, max_companies, log=print):
    links = []
    for p in range(max_dir_pages):
        found = parse_company_links(fetch(with_page(category, p)))
        fresh = [l for l in found if l not in links]
        if not fresh:
            break
        links += fresh
        log(f"Category page {p}: {len(fresh)} companies")
        if len(links) >= max_companies:
            break
    return links[:max_companies]


def scrape_company(fetch, url, max_pages=40):
    seen, rows, expected, idle, name = set(), [], None, 0, url
    for p in range(max_pages):
        name, exp, page_rows = parse_reviews(fetch(with_page(url, p)), url)
        expected = expected or exp
        if not page_rows:
            break
        added = 0
        for r in page_rows:
            key = (r["review_title"], r["reviewer_name"], r["review_date"])
            if key in seen:
                continue
            seen.add(key); rows.append(r); added += 1
        idle = 0 if added else idle + 1
        if idle >= 3 or (expected and len(rows) >= expected):
            break
    return name, expected, rows


KEY_COLS = ("company_url", "review_title", "reviewer_name", "review_date")


def read_raw():
    if not os.path.exists(RAW_CSV):
        return []
    with open(RAW_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_raw(rows):
    """Adds rows to all_reviews.csv, replacing older copies of the same review."""
    os.makedirs(OUT_DIR, exist_ok=True)
    merged = {}
    for r in read_raw() + list(rows):
        merged[tuple(str(r.get(k, "")) for k in KEY_COLS)] = {c: r.get(c, "") for c in COLUMNS}
    with open(RAW_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(merged.values())


def load_done():
    if not os.path.exists(DONE_TXT):
        return set()
    return set(open(DONE_TXT, encoding="utf-8").read().split())


def mark_done(url):
    with open(DONE_TXT, "a", encoding="utf-8") as f:
        f.write(url + "\n")


# ---------------------------------------------------------------- export
def export(min_r, max_r):
    rows = read_raw()
    if not rows:
        print("No data yet. Run a scrape first.")
        return
    keep = []
    for r in rows:
        try:
            if min_r <= float(r["rating"]) <= max_r:
                keep.append(r)
        except (TypeError, ValueError):
            pass
    print(f"{len(keep)} of {len(rows)} reviews match rating {min_r} to {max_r}")
    if not keep:
        return
    path = os.path.join(OUT_DIR, f"reviews_{min_r}-{max_r}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(keep)
    print(f"Saved {path}")


# ---------------------------------------------------------------- run
def run_scrape(category, max_companies=5, max_dir_pages=1, delay=(2, 4),
               log=print, state=None, stop=None, resume=True, save=None):
    """Scrapes every review of the first companies in a category into all_reviews.csv.
    `state` (a dict) is updated with progress so a UI can display it.
    resume=False re-reads every company (used for scheduled refreshes).
    `save(rows)` stores each company's reviews; defaults to output/all_reviews.csv."""
    save = save or append_raw
    state = state if state is not None else {}
    state.update(total=0, done=0, current="", reviews=0, failed=0)
    log("Starting Chrome...")
    driver = start_driver()
    state["state"] = "running"
    fetch = make_fetcher(driver, tuple(delay), stop, log)
    try:
        links = collect_company_links(fetch, category, max_dir_pages, max_companies, log)
        done = load_done() if resume else set()
        state["total"] = len(links)
        log(f"{len(links)} companies selected, {len([l for l in links if l in done])} already done")
        for i, link in enumerate(links, 1):
            if stop is not None and stop.is_set():
                break
            if link in done:
                state["done"] += 1
                continue
            state["current"] = link.rstrip("/").split("/")[-1]
            try:
                name, expected, rows = scrape_company(fetch, link)
            except Stopped:
                break
            except Exception as e:
                log(f"[{i}/{len(links)}] FAILED {link}: {e}")
                state["failed"] = state.get("failed", 0) + 1
                continue
            save(rows)
            mark_done(link)
            state["done"] += 1
            state["reviews"] += len(rows)
            log(f"[{i}/{len(links)}] {name}: {len(rows)} reviews collected (Clutch shows {expected})")
    except Stopped:
        pass
    finally:
        state["current"] = ""
        driver.quit()  # closes the Selenium session; Chrome window can stay open


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", help="Clutch category URL, e.g. https://clutch.co/developers")
    ap.add_argument("--min-rating", type=float, default=0)
    ap.add_argument("--max-rating", type=float, default=5)
    ap.add_argument("--max-companies", type=int, default=5)
    ap.add_argument("--max-dir-pages", type=int, default=1)
    ap.add_argument("--delay", type=float, nargs=2, default=[2, 4], metavar=("MIN", "MAX"))
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args()

    if not (0 <= a.min_rating <= 5 and 0 <= a.max_rating <= 5):
        sys.exit("Ratings must be between 0 and 5.")
    if a.export_only:
        return export(a.min_rating, a.max_rating)
    if not a.category:
        sys.exit("Give --category, or use --export-only.")
    run_scrape(a.category, a.max_companies, a.max_dir_pages, a.delay)
    export(a.min_rating, a.max_rating)


if __name__ == "__main__":
    main()