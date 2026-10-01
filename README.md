# Clutch Review Scraper (Selenium)

Collects reviews from Clutch category pages and keeps those in a chosen rating range.

## Setup (once)
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt

Selenium 4 downloads the matching chromedriver automatically.
If Chrome is not found, set CHROME_PATH to the full path of chrome.exe.

## Run
    python scraper.py --category "https://clutch.co/developers" --min-rating 5 --max-rating 5 --max-companies 5

Other options: --max-dir-pages 2, --delay 2 4 (seconds between pages).

1. A Chrome window opens (its own profile, kept in ./chrome_profile).
2. If a "verify you are human" page appears, solve it once. The script waits.
3. Every review page of every company is read and checked against Clutch's own total.
4. Results: output/all_reviews.csv (all reviews), output/reviews_5.0-5.0.csv/.xlsx (filtered).

Interrupted? Run the same command again. Finished companies (output/done_companies.txt) are skipped.

Change the rating later without scraping again:
    python scraper.py --export-only --min-rating 4.5 --max-rating 5

## Files
- scraper.py        browser control, crawling, resume, export
- clutch_parser.py  HTML -> review rows (edit here if Clutch changes its layout)
