"""Reed.co.uk job search API (free key: https://www.reed.co.uk/developers/jobseeker)."""
from __future__ import annotations

import requests

from ..config import Search
from ..models import Job
from ..text import html_to_text, parse_date
from .http import UA


def parse(data: dict) -> list[Job]:
    jobs = []
    for j in data.get("results", []):
        jobs.append(Job(
            source="reed",
            title=j.get("jobTitle", "").strip(),
            company=j.get("employerName", ""),
            location=j.get("locationName", ""),
            url=j.get("jobUrl", ""),
            apply_url=j.get("jobUrl", ""),
            description=html_to_text(j.get("jobDescription", "")),
            posted_at=parse_date(j.get("date")),
            salary_min=j.get("minimumSalary"), salary_max=j.get("maximumSalary"),
            extra={"snippet_only": True, "reed_id": j.get("jobId")},
        ))
    return jobs


def search(s: Search, key: str) -> list[Job]:
    where = s.locations[0] if s.locations else ""
    jobs: list[Job] = []
    for role in s.roles:
        r = requests.get(
            "https://www.reed.co.uk/api/1.0/search",
            params={"keywords": role, "locationName": where, "distanceFromLocation": 50,
                    "resultsToTake": int(s.reed.get("results_per_role", 50))},
            auth=(key, ""), headers={"User-Agent": UA}, timeout=30,
        )
        r.raise_for_status()
        jobs += parse(r.json())
    return jobs


def full_description(reed_id: int, key: str) -> str:
    r = requests.get(f"https://www.reed.co.uk/api/1.0/jobs/{reed_id}", auth=(key, ""),
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return html_to_text(r.json().get("jobDescription", ""))
