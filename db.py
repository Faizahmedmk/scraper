"""MariaDB storage for collected leads (PyMySQL, pure Python)."""
import hashlib
import threading
from contextlib import contextmanager

import pymysql
import pymysql.cursors

import config

COLUMNS = [
    "company", "company_url", "review_title", "rating", "quality", "schedule",
    "cost", "willing_to_refer", "review_date", "reviewer_name",
    "reviewer_position", "industry", "location", "company_size",
    "project_cost", "project_dates", "services", "quote",
    "project_summary", "feedback_summary", "full_review",
]
NUMERIC = {"rating", "quality", "schedule", "cost", "willing_to_refer"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  review_id CHAR(12) NOT NULL,
  company VARCHAR(255) NOT NULL DEFAULT '',
  company_url VARCHAR(500) NOT NULL DEFAULT '',
  review_title VARCHAR(500) NOT NULL DEFAULT '',
  rating DECIMAL(2,1) NULL,
  quality DECIMAL(2,1) NULL,
  schedule DECIMAL(2,1) NULL,
  cost DECIMAL(2,1) NULL,
  willing_to_refer DECIMAL(2,1) NULL,
  review_date VARCHAR(40) NOT NULL DEFAULT '',
  reviewer_name VARCHAR(255) NOT NULL DEFAULT '',
  reviewer_position VARCHAR(500) NOT NULL DEFAULT '',
  industry VARCHAR(255) NOT NULL DEFAULT '',
  location VARCHAR(255) NOT NULL DEFAULT '',
  company_size VARCHAR(100) NOT NULL DEFAULT '',
  project_cost VARCHAR(100) NOT NULL DEFAULT '',
  project_dates VARCHAR(100) NOT NULL DEFAULT '',
  services TEXT,
  quote TEXT,
  project_summary TEXT,
  feedback_summary TEXT,
  full_review MEDIUMTEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_review (review_id),
  KEY idx_rating (rating),
  KEY idx_company (company_url(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_schema_ready = False
_schema_lock = threading.Lock()


def review_id(row):
    key = "|".join(str(row.get(k) or "") for k in ("company_url", "review_title", "reviewer_name", "review_date"))
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def _connect():
    if not (config.DB_NAME and config.DB_USER):
        raise RuntimeError("Database is not configured: set DB_NAME, DB_USER, DB_PASSWORD (and DB_HOST).")
    return pymysql.connect(host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
                           password=config.DB_PASSWORD, database=config.DB_NAME,
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=10, autocommit=False)


@contextmanager
def cursor():
    global _schema_ready
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if not _schema_ready:
                with _schema_lock:
                    cur.execute(SCHEMA)
                    _schema_ready = True
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _clean(row):
    out = {}
    for c in COLUMNS:
        v = row.get(c)
        if v is None or (isinstance(v, float) and v != v):
            v = None
        if c in NUMERIC:
            try:
                v = float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                v = None
        elif v is None:
            v = ""
        out[c] = v
    out["review_id"] = review_id(out)
    return out


def upsert_leads(rows):
    """Insert new reviews, update existing ones (matched on review_id). Returns rows processed."""
    cleaned = [_clean(r) for r in rows if r.get("company_url") or r.get("review_title")]
    if not cleaned:
        return 0
    cols = ["review_id"] + COLUMNS
    sql = (f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           "ON DUPLICATE KEY UPDATE " + ", ".join(f"{c}=VALUES({c})" for c in COLUMNS))
    with cursor() as cur:
        for i in range(0, len(cleaned), 200):
            cur.executemany(sql, [[r[c] for c in cols] for r in cleaned[i:i + 200]])
    return len(cleaned)


def stats(lo, hi):
    with cursor() as cur:
        cur.execute("SELECT COUNT(*) n, COUNT(DISTINCT company_url) c FROM leads")
        t = cur.fetchone()
        cur.execute("SELECT COUNT(*) n, AVG(rating) a FROM leads WHERE rating BETWEEN %s AND %s", (lo, hi))
        m = cur.fetchone()
        cur.execute("SELECT rating, COUNT(*) n FROM leads WHERE rating IS NOT NULL GROUP BY rating")
        dist = [(float(r["rating"]), r["n"]) for r in cur.fetchall()]
    return {"total": t["n"], "companies": t["c"], "matching": m["n"],
            "avg": round(float(m["a"]), 2) if m["a"] is not None else None, "dist": dist}


def fetch(lo, hi, limit=None):
    sql = "SELECT * FROM leads WHERE rating BETWEEN %s AND %s ORDER BY rating DESC, id DESC"
    args = [lo, hi]
    if limit:
        sql += " LIMIT %s"
        args.append(limit)
    with cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    for r in rows:
        for k in NUMERIC:
            if r[k] is not None:
                r[k] = float(r[k])
        r["last_updated"] = r.pop("updated_at").strftime("%Y-%m-%d %H:%M")
        r.pop("created_at", None)
        r.pop("id", None)
    return rows


def clear():
    with cursor() as cur:
        cur.execute("TRUNCATE TABLE leads")


def import_csv(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return upsert_leads(list(csv.DictReader(f)))


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "init":
        with cursor() as cur:
            cur.execute("SELECT COUNT(*) n FROM leads")
            print("OK, leads table ready,", cur.fetchone()["n"], "rows")
    elif len(sys.argv) == 3 and sys.argv[1] == "import-csv":
        print("Imported", import_csv(sys.argv[2]), "rows")
    else:
        print("usage: python db.py init | python db.py import-csv output/all_reviews.csv")
