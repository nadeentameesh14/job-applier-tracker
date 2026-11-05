"""Hard filters applied before any AI scoring. Each returns a reason string when a job is rejected."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .config import Search
from .models import Job

# Words that mean "this role is in another country" when no UK place is named.
_NON_UK = re.compile(
    r"\b(USA|United States|New York|San Francisco|NYC|Remote - US|Canada|Toronto|Germany|Berlin|Paris|France|"
    r"Amsterdam|Netherlands|Spain|Barcelona|Madrid|Lisbon|Portugal|Dublin|Ireland|India|Bangalore|Singapore|"
    r"Australia|Sydney|Poland|Warsaw|Romania|Mexico|Brazil|Tel Aviv|Israel|Dubai|EMEA only)\b",
    re.I,
)
_UK = re.compile(r"\b(UK|U\.K\.|United Kingdom|England|GB|Great Britain)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower())


def title_matches(title: str, roles: list[str]) -> int | None:
    """Return the priority index of the first role whose words all appear in the title, else None."""
    t = f" {_norm(title)} "
    for i, role in enumerate(roles):
        words = _norm(role).split()
        if words and all(f" {w} " in t for w in words):
            return i
    # common abbreviations
    aliases = {"machine learning": "ml", "artificial intelligence": "ai"}
    for i, role in enumerate(roles):
        r = _norm(role)
        for long, short in aliases.items():
            r = r.replace(long, short)
        words = r.split()
        tt = t
        for long, short in aliases.items():
            tt = tt.replace(long, short)
        if words and all(f" {w} " in tt for w in words):
            return i
    return None


def location_rank(job: Job, s: Search) -> int | None:
    """0 = first preferred location, higher = less preferred, len(locations) = remote. None = rejected."""
    loc = job.location or ""
    low = loc.lower()
    for i, place in enumerate(s.locations):
        if place.lower() in low:
            return i
    is_remote = job.remote or "remote" in low or "anywhere" in low
    if s.remote_ok and is_remote:
        if _UK.search(loc) or not _NON_UK.search(loc):
            return len(s.locations)
    return None


def reject_reason(job: Job, s: Search, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    if any(c.lower() == job.company.strip().lower() for c in s.exclude_companies):
        return "excluded company"
    if title_matches(job.title, s.roles) is None:
        return "title not in target roles"
    for w in s.exclude_title_words:
        if re.search(rf"\b{re.escape(w)}\b", job.title, re.I):
            return f"title contains '{w}'"
    if location_rank(job, s) is None:
        return f"location '{job.location}' not in target area"
    if job.posted_at and (now - job.posted_at).days > s.max_age_days:
        return f"posted {(now - job.posted_at).days} days ago"
    if s.min_salary and job.salary_max and not job.extra.get("salary_is_predicted"):
        if job.salary_max < s.min_salary:
            return f"salary up to {int(job.salary_max)} below {s.min_salary}"
    return None


def sort_key(job: Job, s: Search):
    """London (first location) first, then role priority, then newest."""
    loc = location_rank(job, s)
    role = title_matches(job.title, s.roles)
    ts = job.posted_at.timestamp() if job.posted_at else 0
    return (0 if loc == 0 else 1, role if role is not None else 99, -ts)


def dedupe(jobs: list[Job]) -> list[Job]:
    """Keep one job per company+title, preferring direct company boards (full description, auto-apply)."""
    pref = {"greenhouse": 0, "lever": 0, "ashby": 0, "linkedin": 1, "reed": 2, "adzuna": 3}
    best: dict[str, Job] = {}
    for j in jobs:
        k = j.dedupe_key
        if k not in best or pref.get(j.source, 5) < pref.get(best[k].source, 5):
            best[k] = j
    return list(best.values())


def apply_filters(jobs: list[Job], s: Search, already_seen: set[str] | None = None):
    """Returns (kept sorted best-first, rejected as list of (job, reason))."""
    already_seen = already_seen or set()
    kept, rejected = [], []
    for j in dedupe(jobs):
        if j.dedupe_key in already_seen:
            rejected.append((j, "already in tracker"))
            continue
        r = reject_reason(j, s)
        if r:
            rejected.append((j, r))
        else:
            kept.append(j)
    kept.sort(key=lambda j: sort_key(j, s))
    return kept, rejected
