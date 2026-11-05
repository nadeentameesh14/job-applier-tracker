"""Job sources. Each returns a list of Job objects and never raises on a single bad board."""
from __future__ import annotations

import logging
import os

from ..config import Settings
from ..models import Job
from . import adzuna, ashby, greenhouse, lever, linkedin, linkedin_alerts, reed

log = logging.getLogger(__name__)

ATS = {"greenhouse": greenhouse.fetch, "lever": lever.fetch, "ashby": ashby.fetch}


def fetch_all(settings: Settings) -> tuple[list[Job], list[str]]:
    """Fetch from every configured source. Returns (jobs, problems)."""
    jobs: list[Job] = []
    problems: list[str] = []
    for c in settings.search.companies:
        try:
            found = ATS[c.ats](c.token, c.name)
            log.info("%s (%s): %d jobs", c.name, c.ats, len(found))
            jobs += found
        except Exception as e:  # one broken board must not stop the run
            problems.append(f"{c.name} ({c.ats}/{c.token}): {e}")
    s = settings.search
    if s.adzuna.get("enabled") and os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"):
        try:
            found = adzuna.search(s, os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"])
            log.info("Adzuna: %d jobs", len(found))
            jobs += found
        except Exception as e:
            problems.append(f"Adzuna: {e}")
    elif s.adzuna.get("enabled"):
        problems.append("Adzuna skipped: ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    if s.reed.get("enabled") and os.environ.get("REED_API_KEY"):
        try:
            found = reed.search(s, os.environ["REED_API_KEY"])
            log.info("Reed: %d jobs", len(found))
            jobs += found
        except Exception as e:
            problems.append(f"Reed: {e}")
    elif s.reed.get("enabled"):
        problems.append("Reed skipped: REED_API_KEY not set")
    if s.linkedin.get("enabled"):
        try:
            found = linkedin.search(s, s.linkedin)
            log.info("LinkedIn: %d jobs", len(found))
            jobs += found
        except Exception as e:
            problems.append(f"LinkedIn: {e}")
    alerts = s.linkedin.get("alert_emails", {}) or {}
    if alerts.get("enabled"):
        addr, pw = os.environ.get("GMAIL_ADDRESS"), os.environ.get("GMAIL_APP_PASSWORD")
        if addr and pw:
            try:
                found = linkedin_alerts.search(addr, pw.replace(" ", ""), alerts)
                log.info("LinkedIn alert emails: %d jobs", len(found))
                jobs += found
            except Exception as e:
                problems.append(f"LinkedIn alert emails: {e}")
        else:
            problems.append("LinkedIn alert emails skipped: GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")
    return jobs, problems
