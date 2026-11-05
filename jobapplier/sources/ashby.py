from __future__ import annotations

import re

from ..models import Job
from ..text import html_to_text, parse_date, parse_salary
from .http import get_json


def parse(data: dict, company: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        lo, hi = parse_salary(comp) if comp else (None, None)
        if lo is None:
            lo, hi = parse_salary(desc)
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        loc = "; ".join(l for l in locs if l)
        jobs.append(Job(
            source="ashby",
            title=j.get("title", "").strip(),
            company=company,
            location=loc,
            url=j.get("jobUrl", ""),
            apply_url=j.get("applyUrl", "") or j.get("jobUrl", ""),
            description=desc,
            posted_at=parse_date(j.get("publishedAt")),
            salary_min=lo, salary_max=hi,
            remote=bool(j.get("isRemote")) or bool(re.search(r"remote", loc, re.I)),
        ))
    return jobs


def fetch(token: str, company: str) -> list[Job]:
    return parse(get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"), company)
