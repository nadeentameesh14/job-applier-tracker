"""Adzuna UK job search API (free key: https://developer.adzuna.com)."""
from __future__ import annotations

from ..config import Search
from ..models import Job
from ..text import html_to_text, parse_date
from .http import get_json

COUNTRY = {"UK": "gb", "GB": "gb", "US": "us", "IE": "ie"}


def parse(data: dict) -> list[Job]:
    jobs = []
    for j in data.get("results", []):
        loc = (j.get("location") or {}).get("display_name", "")
        jobs.append(Job(
            source="adzuna",
            title=html_to_text(j.get("title", "")),
            company=(j.get("company") or {}).get("display_name", ""),
            location=loc,
            url=j.get("redirect_url", ""),
            apply_url=j.get("redirect_url", ""),
            description=html_to_text(j.get("description", "")),
            posted_at=parse_date(j.get("created")),
            salary_min=j.get("salary_min"), salary_max=j.get("salary_max"),
            remote="remote" in (j.get("title", "") + loc).lower(),
            extra={"snippet_only": True, "salary_is_predicted": j.get("salary_is_predicted") == "1"},
        ))
    return jobs


def search(s: Search, app_id: str, app_key: str) -> list[Job]:
    cc = COUNTRY.get(s.country.upper(), "gb")
    where = s.locations[0] if s.locations else ""
    jobs: list[Job] = []
    for role in s.roles:
        params = {
            "app_id": app_id, "app_key": app_key,
            "what_phrase": role, "where": where, "distance": 80,  # km, roughly an hour out
            "max_days_old": s.max_age_days,
            "results_per_page": int(s.adzuna.get("results_per_role", 50)),
            "sort_by": "date", "content-type": "application/json",
        }
        jobs += parse(get_json(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1", params=params))
    return jobs
