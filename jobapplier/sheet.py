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


def sync() -> str:
    url, token = os.environ.get("SHEET_WEBHOOK_URL", "").strip(), os.environ.get("SHEET_TOKEN", "").strip()
    if not url:
        return "No Google Sheet set up (add the SHEET_WEBHOOK_URL and SHEET_TOKEN secrets to turn it on)."
    tabs = {}
    t = _tab(DATA / "tracker.csv", key="job_id")
    if t:
        tabs["Tracker"] = t
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
