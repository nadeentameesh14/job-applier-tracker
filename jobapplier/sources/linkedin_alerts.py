"""LinkedIn job-alert emails, read from Gmail over IMAP.

Set up saved searches with alerts on LinkedIn (daily, by email). The bot reads the alert emails
from the last few days, collects the job links, and looks each job up on LinkedIn's public page.
Needs two secrets: GMAIL_ADDRESS and GMAIL_APP_PASSWORD (a Google "app password", not your normal one).
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import Message

from ..models import Job
from . import linkedin

log = logging.getLogger(__name__)

SENDERS = ("jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com", "jobs-listings@linkedin.com")
_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?\"'\s]*?-)?(\d{6,})")


def _bodies(msg: Message) -> str:
    parts = []
    for p in msg.walk():
        if p.get_content_type() in ("text/html", "text/plain"):
            try:
                parts.append(p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
    return "\n".join(parts)


def job_ids(text: str) -> list[str]:
    seen, out = set(), []
    for m in _ID.finditer(text.replace("=\n", "").replace("%2F", "/")):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def fetch_ids(address: str, password: str, days: int = 3) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    ids: list[str] = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as M:
        M.login(address, password)
        M.select('"[Gmail]/All Mail"', readonly=True)
        nums: list[bytes] = []
        for sender in SENDERS:  # alerts sent or auto-forwarded straight from LinkedIn
            typ, data = M.search(None, "FROM", f'"{sender}"', "SINCE", since)
            nums += data[0].split() if typ == "OK" and data and data[0] else []
        # alerts forwarded by hand come "from" you, so also look for LinkedIn job links in the text
        typ, data = M.search(None, "X-GM-RAW", f'"jobalerts-noreply@linkedin.com newer_than:{days}d"')
        nums += data[0].split() if typ == "OK" and data and data[0] else []
        for num in dict.fromkeys(nums):
            typ, msg = M.fetch(num, "(BODY.PEEK[])")
            if typ == "OK" and msg and isinstance(msg[0], tuple):
                for jid in job_ids(_bodies(email.message_from_bytes(msg[0][1]))):
                    if jid not in ids:
                        ids.append(jid)
    return ids


def search(address: str, password: str, opts: dict) -> list[Job]:
    ids = fetch_ids(address, password, int(opts.get("days", 3)))[: int(opts.get("max_jobs", 60))]
    log.info("LinkedIn alerts: %d job links", len(ids))
    jobs: list[Job] = []
    for jid in ids:
        try:
            j = linkedin.job_from_id(jid)
            if j:
                jobs.append(j)
        except linkedin.RateLimited as e:
            log.warning("%s; keeping %d alert jobs", e, len(jobs))
            break
        except Exception as e:
            log.info("alert job %s: %s", jid, e)
        time.sleep(linkedin.PAUSE)
    return jobs
