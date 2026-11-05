from __future__ import annotations

import requests

UA = "job-applier-tracker/0.1 (+https://github.com/nadeentameesh14/job-applier-tracker)"


def get_json(url: str, **kw):
    r = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def get_text(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text
