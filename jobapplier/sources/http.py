from __future__ import annotations

import requests

UA = "job-applier-tracker/0.1 (+https://github.com/nadeentameesh14/job-applier-tracker)"


def get_json(url: str, **kw):
    """GET JSON, retrying once on a timeout (big boards like Lever's can be slow)."""
    for attempt in (1, 2):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=90, **kw)
            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise


def get_text(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text
