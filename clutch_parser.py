"""Parses Clutch HTML into review rows. No browser code in here."""
import re
from bs4 import BeautifulSoup

COLUMNS = [
    "company", "company_url", "review_title", "rating", "quality", "schedule",
    "cost", "willing_to_refer", "review_date", "reviewer_name",
    "reviewer_position", "industry", "location", "company_size",
    "project_cost", "project_dates", "services", "quote",
    "project_summary", "feedback_summary", "full_review",
]


def _txt(node, sel):
    el = node.select_one(sel)
    return el.get_text(" ", strip=True) if el else ""


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _side(card, icon_cls):
    el = card.select_one("span." + icon_cls)
    return el.parent.get_text(" ", strip=True) if el else ""


def _parse_card(card, company, url):
    row = {c: "" for c in COLUMNS}
    row.update(company=company, company_url=url)
    row["review_title"] = _txt(card, ".profile-review__header h3")
    row["rating"] = _num(_txt(card, ".profile-review__rating .sg-rating__number"))
    for dl in card.select(".profile-review__rating-metrics dl"):
        key = _txt(dl, "dt").lower().replace(" ", "_")
        if key in ("quality", "schedule", "cost", "willing_to_refer"):
            row[key] = _num(_txt(dl, "dd"))
    row["review_date"] = _txt(card, ".profile-review__date")
    row["reviewer_name"] = _txt(card, ".reviewer_card--name")
    row["reviewer_position"] = _txt(card, ".reviewer_position")
    row["industry"] = _side(card, "icon_industry")
    row["location"] = _side(card, "icon_pin")
    row["company_size"] = _side(card, "icon_person__heavy")
    row["project_cost"] = _side(card, "icon_tag")
    row["project_dates"] = _side(card, "icon_calendar")
    row["services"] = _txt(card, ".service-lines")
    row["quote"] = _txt(card, ".profile-review__quote")
    row["project_summary"] = _txt(card, ".profile-review__summary")
    row["feedback_summary"] = _txt(card, ".profile-review__feedback")
    row["full_review"] = _txt(card, ".profile-review__extra")
    return row


def parse_company_links(html, base="https://clutch.co"):
    """Company profile URLs from a category (directory) page."""
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a.provider__title-link"):
        href = a.get("href")
        if href:
            links.append(urljoin(base, href).split("?")[0].split("#")[0])
    return list(dict.fromkeys(links))


def parse_reviews(html, company_url):
    """Returns (company_name, expected_total_or_None, [rows]) for one profile page."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.select_one("h1")
    company = h1.get_text(strip=True) if h1 else company_url.rstrip("/").split("/")[-1]
    title = soup.title.get_text() if soup.title else ""
    m = re.search(r"Reviews \((\d+)\)", title)
    expected = int(m.group(1)) if m else None
    rows = [_parse_card(c, company, company_url)
            for c in soup.select("article.profile-review")]
    return company, expected, rows
