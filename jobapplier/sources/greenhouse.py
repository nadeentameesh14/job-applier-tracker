from __future__ import annotations

from ..models import Job
from ..text import html_to_text, parse_date, parse_salary
from .http import get_json


def parse(data: dict, company: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        desc = html_to_text(j.get("content", ""))
        lo, hi = parse_salary(desc)
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(Job(
            source="greenhouse",
            title=j.get("title", "").strip(),
            company=company or j.get("company_name", ""),
            location=loc,
            url=j.get("absolute_url", ""),
            apply_url=j.get("absolute_url", ""),
            description=desc,
            posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
            salary_min=lo, salary_max=hi,
            remote="remote" in loc.lower(),
        ))
    return jobs


def fetch(token: str, company: str) -> list[Job]:
    return parse(get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"), company)
