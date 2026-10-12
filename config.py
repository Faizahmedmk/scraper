"""Settings from environment variables (cPanel 'Setup Python App' -> Environment variables).
A local .env file (KEY=VALUE per line) is also read, without overriding real env vars."""
import os

_here = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8-sig"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv(os.path.join(_here, ".env"))

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

APP_USER = os.environ.get("APP_USER", "admin")      # dashboard login
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")   # required on the server
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")  # shared secret for POST /api/ingest

# Chrome-based scraping from the web UI. Normally off on cPanel (no Chrome / display there).
ENABLE_SCRAPER = os.environ.get("ENABLE_SCRAPER", "0") == "1"
