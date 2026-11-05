from __future__ import annotations

from ..models import Job
from ..text import html_to_text, parse_date, parse_salary
from .http import get_json


def parse(data: list, company: str) -> list[Job]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description", ""))]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", ""))
            parts.append(html_to_text(lst.get("content", "")))
        parts.append(j.get("additionalPlain") or "")
        desc = "\n".join(p for p in parts if p).strip()
        rng = j.get("salaryRange") or {}
        lo, hi = rng.get("min"), rng.get("max")
        if lo is None:
            lo, hi = parse_salary(desc)
        loc = cats.get("location", "") or ", ".join(cats.get("allLocations") or [])
        jobs.append(Job(
            source="lever",
            title=j.get("text", "").strip(),
            company=company,
            location=loc,
            url=j.get("hostedUrl", ""),
            apply_url=j.get("applyUrl", "") or j.get("hostedUrl", ""),
            description=desc,
            posted_at=parse_date(j.get("createdAt")),
            salary_min=lo, salary_max=hi,
            remote=(j.get("workplaceType") == "remote") or "remote" in loc.lower(),
        ))
    return jobs


def fetch(token: str, company: str) -> list[Job]:
    return parse(get_json(f"https://api.lever.co/v0/postings/{token}?mode=json"), company)
