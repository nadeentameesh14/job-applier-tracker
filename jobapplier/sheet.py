"""Copy the tracker (and every score) into your Google Sheet, through a small Apps Script web app you
add to the sheet once (helper/google_sheet.gs). Your own notes and Interview/Offer/Rejected statuses
in the sheet are kept."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import requests

DATA = Path("data")


def _tab(path: Path, key: str | None = None, newest_first: bool = False) -> dict | None:
    if not path.exists():
        return None
    rows = list(csv.reader(path.open(newline="")))
    if not rows:
        return None
    header, body = rows[0], rows[1:]
    if newest_first:
        body = body[::-1]
    return {"header": header, "rows": body, "key": key}


FIRST = ["status", "company", "title", "date_applied", "link", "location", "notes", "fit_score", "salary_listed"]
ORDER = ["Needs you", "Apply on company site", "Applied", "Awaiting approval", "Ready to auto-apply"]


def _readable(tab: dict) -> dict:
    """Put what you look at first on the left (status, company, role, date applied, link) and sort the jobs
    so the ones needing you come first, then applied ones, newest first within each group."""
    h = tab["header"]
    cols = [c for c in FIRST if c in h] + [c for c in h if c not in FIRST]
    idx = [h.index(c) for c in cols]
    rows = [[r[i] if i < len(r) else "" for i in idx] for r in tab["rows"]]
    si, di, fi = cols.index("status") if "status" in cols else None, \
        cols.index("date_applied") if "date_applied" in cols else None, cols.index("date_found") if "date_found" in cols else None
    if si is not None:
        rank = lambda r: ORDER.index(r[si]) if r[si] in ORDER else len(ORDER)
        rows.sort(key=lambda r: (r[di] if di is not None else "") or (r[fi] if fi is not None else ""), reverse=True)
        rows.sort(key=rank)  # stable: keeps newest first inside each status
    return {**tab, "header": cols, "rows": rows}


def sync() -> str:
    url, token = os.environ.get("SHEET_WEBHOOK_URL", "").strip(), os.environ.get("SHEET_TOKEN", "").strip()
    if not url:
        return "No Google Sheet set up (add the SHEET_WEBHOOK_URL and SHEET_TOKEN secrets to turn it on)."
    tabs = {}
    t = _tab(DATA / "tracker.csv", key="job_id")
    if t:
        tabs["Tracker"] = _readable(t)
    s = _tab(DATA / "scores.csv", newest_first=True)
    if s:
        tabs["Scores"] = s
    if not tabs:
        return "Nothing to send to the sheet yet."
    r = requests.post(url, data=json.dumps({"token": token, "tabs": tabs}),
                      headers={"Content-Type": "application/json"}, timeout=120)
    try:
        res = r.json()
    except Exception:
        return f"The Google Sheet didn't answer as expected (HTTP {r.status_code}). Check the web app URL and that it's deployed for 'Anyone'."
    if not res.get("ok"):
        return f"The Google Sheet refused the update: {res.get('error')} (check SHEET_TOKEN matches TOKEN in the script)."
    return f"Google Sheet updated: {res.get('url', '')}"
