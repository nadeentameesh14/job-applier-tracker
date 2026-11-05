"""LinkedIn's public job search: the pages anyone can see without logging in.

No LinkedIn account, cookie or password is used, so your account is never at risk. LinkedIn may
slow down or block a server that asks too often, so the search is small and polite: a few pages
per role, with a pause between requests, and it stops at the first sign of rate limiting.
"""
from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

from ..config import Search
from ..models import Job
from ..text import html_to_text, parse_date, parse_salary

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
# A normal browser string: LinkedIn serves its public pages to browsers, not to named bots.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")
PAUSE = 2.0  # seconds between requests


class RateLimited(Exception):
    pass


def _get(url: str, params: dict | None = None) -> str:
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"}, timeout=30)
    if r.status_code in (429, 999):
        raise RateLimited(f"LinkedIn rate limit (HTTP {r.status_code})")
    if r.status_code == 400 and "start" in (params or {}):
        return ""  # past the last page
    r.raise_for_status()
    return r.text


def job_id_from(s: str) -> str | None:
    m = re.search(r"jobPosting:(\d+)", s) or re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)", s) or re.search(r"currentJobId=(\d+)", s)
    return m.group(1) if m else None


def parse_cards(html: str, remote: bool = False) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card, div.job-search-card, li > div[data-entity-urn]"):
        jid = job_id_from(card.get("data-entity-urn", "")) or job_id_from(str(card.select_one("a")))
        title = card.select_one(".base-search-card__title, h3")
        company = card.select_one(".base-search-card__subtitle, h4")
        if not (jid and title and company):
            continue
        loc = card.select_one(".job-search-card__location")
        when = card.select_one("time")
        sal = card.select_one(".job-search-card__salary-info")
        lo, hi = parse_salary(sal.get_text(" ", strip=True)) if sal else (None, None)
        url = f"https://www.linkedin.com/jobs/view/{jid}/"
        loc_text = loc.get_text(" ", strip=True) if loc else ""
        jobs.append(Job(
            source="linkedin",
            title=title.get_text(" ", strip=True),
            company=company.get_text(" ", strip=True),
            location=loc_text,
            url=url,
            apply_url=url,
            posted_at=parse_date(when.get("datetime")) if when else None,
            salary_min=lo, salary_max=hi,
            remote=remote or "remote" in loc_text.lower(),
            extra={"snippet_only": True, "linkedin_id": jid},
        ))
    return jobs


def parse_detail(html: str) -> dict:
    """Full description, and where the Apply button goes: LinkedIn itself (Easy Apply) or the company site."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".show-more-less-html__markup, .description__text")
    out = {"description": html_to_text(str(body)) if body else "", "easy_apply": None, "apply_url": ""}
    code = soup.select_one("code#applyUrl")
    if code:
        raw = unescape(code.decode_contents())
        m = re.search(r'"(https?://[^"]+)"', raw) or re.search(r"(https?://\S+)", raw)
        if m:
            u = m.group(1)
            inner = re.search(r"[?&]url=([^&]+)", u)
            out["apply_url"] = unquote(inner.group(1)) if inner else u
            out["easy_apply"] = False
    if out["easy_apply"] is None:
        btn = soup.select_one("[data-tracking-control-name*=apply]")
        ctl = btn.get("data-tracking-control-name", "") if btn else ""
        if "offsite" in ctl:
            out["easy_apply"] = False
        elif "onsite" in ctl or "easy apply" in soup.get_text(" ").lower():
            out["easy_apply"] = True
    crit = {h.get_text(" ", strip=True): v.get_text(" ", strip=True)
            for h, v in ((li.select_one("h3"), li.select_one("span"))
                         for li in soup.select("li.description__job-criteria-item")) if h and v}
    for key, sel in (("title", ".top-card-layout__title, h2"), ("company", ".topcard__org-name-link, .topcard__flavor a"),
                     ("location", ".topcard__flavor--bullet"), ("posted", ".posted-time-ago__text")):
        el = soup.select_one(sel)
        out[key] = el.get_text(" ", strip=True) if el else ""
    out["seniority"] = crit.get("Seniority level", "")
    out["employment_type"] = crit.get("Employment type", "")
    return out


def ago_to_date(text: str):
    """'3 days ago' / '2 weeks ago' / '5 hours ago' -> an aware datetime (None if not understood)."""
    from datetime import datetime, timedelta, timezone
    m = re.search(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", text or "", re.I)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
    return datetime.now(timezone.utc) - timedelta(days=days)


def job_from_id(jid: str) -> Job | None:
    """Build a job from its LinkedIn id alone (used for job-alert emails)."""
    d = parse_detail(_get(DETAIL.format(id=jid)))
    if not (d["title"] and d["company"]):
        return None
    url = f"https://www.linkedin.com/jobs/view/{jid}/"
    job = Job(source="linkedin", title=d["title"], company=d["company"], location=d["location"], url=url,
              apply_url=url, description=d["description"][:20000], posted_at=ago_to_date(d["posted"]),
              remote="remote" in d["location"].lower(),
              extra={"snippet_only": False, "linkedin_id": jid, "via": "alert email"})
    lo, hi = parse_salary(d["description"])
    job.salary_min, job.salary_max = lo, hi
    if d["easy_apply"] is not None:
        job.extra["easy_apply"] = d["easy_apply"]
    if d["apply_url"] and "linkedin.com" not in d["apply_url"]:
        job.apply_url = d["apply_url"]
    return job


def full_details(job: Job) -> Job:
    """Fetch the job page: full description, Easy Apply or not, and the company's own apply link."""
    jid = job.extra.get("linkedin_id")
    if not jid or not job.extra.get("snippet_only"):
        return job
    d = parse_detail(_get(DETAIL.format(id=jid)))
    if len(d["description"]) > len(job.description):
        job.description = d["description"][:20000]
        job.extra["snippet_only"] = False
    if d["easy_apply"] is not None:
        job.extra["easy_apply"] = d["easy_apply"]
    if d["apply_url"] and "linkedin.com" not in d["apply_url"]:
        job.apply_url = d["apply_url"]  # applying happens on the company's site
    for k in ("seniority", "employment_type"):
        if d.get(k):
            job.extra[k] = d[k]
    return job


def search(s: Search, opts: dict) -> list[Job]:
    pages = int(opts.get("pages_per_role", 2))
    miles = int(opts.get("distance_miles", 25))
    seconds = max(1, s.max_age_days) * 86400
    where = s.locations[0] if s.locations else "United Kingdom"
    country = {"UK": "United Kingdom"}.get(s.country, s.country)
    searches = [({"location": where, "distance": miles}, False)]
    if s.remote_ok:
        searches.append(({"location": country, "f_WT": "2"}, True))
    jobs: list[Job] = []
    try:
        for role in s.roles:
            for extra, remote in searches:
                for page in range(pages):
                    params = {"keywords": role, "f_TPR": f"r{seconds}", "sortBy": "DD", "start": page * 25, **extra}
                    if opts.get("easy_apply_only"):
                        params["f_AL"] = "true"
                    html = _get(SEARCH, params)
                    found = parse_cards(html, remote) if html.strip() else []
                    jobs += found
                    time.sleep(PAUSE)
                    if len(found) < 10:
                        break
    except RateLimited as e:
        if not jobs:
            raise
        log.warning("%s; keeping the %d jobs found so far", e, len(jobs))
    return jobs
