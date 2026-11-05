"""The morning email: what the run found, what it applied to, what's queued, and what needs you.

Sent from the Gmail address in the GMAIL_ADDRESS / GMAIL_APP_PASSWORD secrets (the same ones used to
read LinkedIn alert emails) to digest.to in settings (or your profile email).
"""
from __future__ import annotations

import csv
import html
import json
import os
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from . import tracker as T
from .config import Settings

DATA = Path("data")
E = html.escape


def _rows() -> list[dict]:
    p = DATA / "tracker.csv"
    return list(csv.DictReader(p.open(newline=""))) if p.exists() else []


def _queue() -> list[dict]:
    """Everything in the apply queue, with the advert details."""
    out = []
    for f in sorted((DATA / "applications").glob("*/application.json")):
        try:
            a = json.loads(f.read_text())
            j = json.loads((f.parent / "job.json").read_text()) if (f.parent / "job.json").exists() else {}
        except Exception:
            continue
        out.append({**a, "job": j, "folder": f.parent.name})
    return out


def _links(settings: Settings) -> dict[str, str]:
    server, repo, run = os.environ.get("GITHUB_SERVER_URL", "https://github.com"), os.environ.get("GITHUB_REPOSITORY", ""), \
        os.environ.get("GITHUB_RUN_ID", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    gh = f"{server}/{repo}" if repo else ""
    return {
        "tracker": settings.digest.get("tracker_url") or settings.sheet.get("url") or os.environ.get("SHEET_URL", "")
                   or (f"{gh}/blob/{branch}/data/tracker.csv" if gh else ""),
        "tracker_csv": f"{gh}/blob/{branch}/data/tracker.csv" if gh else "",
        "scores": f"{gh}/blob/{branch}/data/scores.csv" if gh else "",
        "run": f"{gh}/actions/runs/{run}" if gh and run else "",
        "apps": f"{gh}/tree/{branch}/data/applications" if gh else "",
    }


def _money(v) -> str:
    try:
        return f"£{int(float(v)):,}"
    except Exception:
        return str(v or "")


def build(settings: Settings, log_tail: str = "") -> tuple[str, str, str]:
    """Returns (subject, plain text, html)."""
    stats = {}
    if (DATA / "last_run.json").exists():
        stats = json.loads((DATA / "last_run.json").read_text())
    rows = _rows()
    queue = _queue()
    links = _links(settings)
    today = date.today()
    since = (today - timedelta(days=1)).isoformat()

    q_linkedin = [q for q in queue if q.get("apply_method") == "linkedin" and q.get("status") == T.AWAITING_APPROVAL]
    q_auto = [q for q in queue if q.get("apply_method") == "auto" and q.get("status") == T.READY_AUTO]
    q_offsite = [q for q in queue if q.get("apply_method") == "manual" and q.get("status") == T.AWAITING_APPROVAL]
    fit = {r["job_id"]: r for r in rows}
    for lst in (q_linkedin, q_auto, q_offsite):
        lst.sort(key=lambda q: -int(fit.get(q["job_id"], {}).get("fit_score") or 0))
    applied_recent = [r for r in rows if r.get("status") == T.APPLIED and (r.get("date_applied") or "") >= since]
    needs_you = [r for r in rows if r.get("status") in ("Needs you", "Apply on company site")]
    total_applied = sum(1 for r in rows if r.get("status") in (T.APPLIED, T.INTERVIEW, T.OFFER, T.REJECTED))
    interviews = sum(1 for r in rows if r.get("status") in (T.INTERVIEW, T.OFFER))

    queued = stats.get("queued", {})
    n_queued = sum(queued.values()) if queued else 0
    subject = (f"Job bot {today.strftime('%a %d %b')}: {stats.get('fetched', 0)} scanned, {stats.get('suited', 0)} suited, "
               f"{n_queued} queued, {len(applied_recent)} applied")
    if stats.get("stopped_early"):
        subject += " (run stopped early)"

    # ---------- html ----------
    css_card = "display:inline-block;min-width:110px;margin:4px;padding:10px 12px;border:1px solid #e3e3e3;border-radius:8px"
    def card(n, label):
        return f"<div style='{css_card}'><div style='font-size:22px;font-weight:600'>{E(str(n))}</div><div style='color:#666;font-size:12px'>{E(label)}</div></div>"

    def table(head: list[str], body: list[list[str]]) -> str:
        if not body:
            return "<p style='color:#888'>None.</p>"
        th = "".join(f"<th style='text-align:left;padding:6px;border-bottom:1px solid #ddd;font-size:12px;color:#555'>{E(h)}</th>" for h in head)
        trs = "".join("<tr>" + "".join(f"<td style='padding:6px;border-bottom:1px solid #f0f0f0;font-size:13px;vertical-align:top'>{c}</td>" for c in r) + "</tr>" for r in body)
        return f"<table style='border-collapse:collapse;width:100%'><tr>{th}</tr>{trs}</table>"

    def job_rows(lst):
        out = []
        for q in lst:
            j, r = q.get("job", {}), fit.get(q["job_id"], {})
            url = j.get("url") or q.get("apply_url", "")
            sal = ""
            if j.get("salary_min") or j.get("salary_max"):
                sal = "–".join(_money(v) for v in (j.get("salary_min"), j.get("salary_max")) if v)
            missing = (r.get("missing_keywords") or "")[:120]
            out.append([E(str(r.get("fit_score", ""))), f"<a href='{E(url)}'>{E(j.get('title') or r.get('title', ''))}</a>",
                        E(j.get("company") or r.get("company", "")), E(j.get("location", "")), E(sal),
                        E((j.get("posted_at") or "")[:10]), E(missing)])
        return out

    head = ["Fit", "Role", "Company", "Location", "Salary", "Posted", "Missing keywords"]
    filtered = stats.get("filtered_out", {})
    filt_html = "".join(f"<li>{E(str(n))} × {E(k)}</li>" for k, n in list(filtered.items())[:10]) or "<li>none</li>"
    src_html = ", ".join(f"{E(k)}: {v}" for k, v in (stats.get("by_source") or {}).items()) or "n/a"
    probs = stats.get("source_problems") or []

    parts = [f"<div style='font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:860px;color:#222'>",
             f"<h2 style='margin:0 0 4px'>Your job bot, {E(today.strftime('%A %d %B'))}</h2>"]
    if stats.get("test"):
        parts.append("<p style='color:#b45309'>This was a small test run.</p>")
    if stats.get("stopped_early"):
        parts.append(f"<p style='color:#b91c1c'><b>The run stopped early:</b> {E(stats['stopped_early'])}</p>")
    if not stats:
        parts.append("<p style='color:#b91c1c'><b>Today's run didn't finish, so the numbers below are from the tracker only.</b></p>")
    parts.append("<div>" + card(stats.get("fetched", "–"), "jobs scanned") + card(stats.get("matched", "–"), "matched your filters")
                 + card(stats.get("screened", "–"), "scored by Claude") + card(stats.get("suited", "–"), f"suited (fit ≥ {stats.get('min_fit_score', settings.min_fit_score)})")
                 + card(n_queued, "tailored and queued") + card(len(applied_recent), "applied since yesterday") + "</div>")
    parts.append(f"<p>All time: <b>{total_applied}</b> applications, <b>{interviews}</b> interviews or offers. "
                 + (f"<a href='{E(links['tracker'])}'>Open your tracker</a>" if links["tracker"] else "") + "</p>")

    parts.append("<h3>What happens at 9am on your laptop</h3><ul>"
                 f"<li><b>{len(q_auto)}</b> company career-site applications go in automatically.</li>"
                 f"<li><b>{len(q_offsite)}</b> LinkedIn jobs that apply on a company site: the helper finds the real link and applies if it's a site it supports (otherwise it lists them for you).</li>"
                 f"<li><b>{len(q_linkedin)}</b> LinkedIn Easy Apply jobs wait for your one-click approval on the page that opens.</li></ul>")
    parts.append(f"<h3>LinkedIn Easy Apply jobs waiting for your approval ({len(q_linkedin)})</h3>" + table(head, job_rows(q_linkedin)))
    parts.append(f"<h3>LinkedIn jobs that apply on the company site ({len(q_offsite)})</h3>" + table(head, job_rows(q_offsite)))
    parts.append(f"<h3>Company career sites, applied automatically ({len(q_auto)})</h3>" + table(head, job_rows(q_auto)))
    parts.append(f"<h3>Applied since yesterday ({len(applied_recent)})</h3>" + table(
        ["Applied", "Role", "Company", "Fit", "How"],
        [[E(r.get("date_applied", "")), f"<a href='{E(r.get('link', ''))}'>{E(r.get('title', ''))}</a>", E(r.get("company", "")),
          E(r.get("fit_score", "")), E(r.get("apply_method", ""))] for r in applied_recent]))
    parts.append(f"<h3>Needs you ({len(needs_you)})</h3>" + table(
        ["Status", "Role", "Company", "What's needed"],
        [[E(r.get("status", "")), f"<a href='{E(r.get('link', ''))}'>{E(r.get('title', ''))}</a>", E(r.get("company", "")),
          E((r.get("notes") or "")[:300])] for r in needs_you]))
    parts.append("<h3>How the numbers break down</h3><ul>"
                 f"<li>Sources: {src_html}</li>"
                 f"<li>Filtered out before scoring:<ul>{filt_html}</ul></li>"
                 f"<li>Scored below {stats.get('min_fit_score', settings.min_fit_score)}: {stats.get('below_threshold', '–')}; "
                 f"ruled out by a deal-breaker (e.g. clearance, sponsorship): {stats.get('deal_breakers', '–')}</li>"
                 f"<li>Suited but over today's cap (kept for tomorrow): {stats.get('over_cap', '–')}; "
                 f"not scored today (over the scoring limit): {stats.get('not_screened', '–')}</li></ul>")
    if probs:
        parts.append("<p style='color:#b45309'>Source problems: " + E("; ".join(map(str, probs))[:600]) + "</p>")
    lk = " · ".join(f"<a href='{E(u)}'>{E(n)}</a>" for n, u in
                    [("Tracker", links["tracker"]), ("Every score with reasons", links["scores"]),
                     ("Tailored CVs and reports", links["apps"]), ("Today's run log", links["run"])] if u)
    parts.append(f"<p style='margin-top:20px;font-size:13px'>{lk}</p>")
    if log_tail and (stats.get("stopped_early") or not stats):
        parts.append(f"<pre style='font-size:11px;background:#f6f6f6;padding:8px;white-space:pre-wrap'>{E(log_tail[-3000:])}</pre>")
    parts.append("</div>")
    html_body = "".join(parts)

    # ---------- plain text ----------
    lines = [subject, ""]
    lines.append(f"Scanned {stats.get('fetched', '-')}, matched filters {stats.get('matched', '-')}, scored {stats.get('screened', '-')}, "
                 f"suited {stats.get('suited', '-')}, queued {n_queued}, applied since yesterday {len(applied_recent)}.")
    lines.append(f"Tracker: {links['tracker']}")
    lines.append(f"\nLinkedIn Easy Apply waiting for approval ({len(q_linkedin)}):")
    for q in q_linkedin:
        j = q.get("job", {})
        lines.append(f"  [{fit.get(q['job_id'], {}).get('fit_score', '')}] {j.get('title', '')} at {j.get('company', '')}, {j.get('location', '')}  {j.get('url', '')}")
    lines.append(f"\nNeeds you ({len(needs_you)}):")
    for r in needs_you:
        lines.append(f"  {r.get('title', '')} at {r.get('company', '')}: {(r.get('notes') or '')[:200]}  {r.get('link', '')}")
    return subject, "\n".join(lines), html_body


def send(settings: Settings, log_tail: str = "", dry_run: bool = False) -> str:
    subject, text, html_body = build(settings, log_tail)
    if dry_run:
        out = DATA / "digest_preview.html"
        DATA.mkdir(exist_ok=True)
        out.write_text(html_body)
        return f"Wrote {out} (not sent). Subject: {subject}"
    user, pw = os.environ.get("GMAIL_ADDRESS", "").strip(), os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    to = settings.digest.get("to") or settings.profile.get("email") or user
    if not (user and pw and to):
        return "No email sent: add the GMAIL_ADDRESS and GMAIL_APP_PASSWORD secrets (docs/SETUP.md)."
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Job bot <{user}>", to
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    return f"Sent the morning email to {to}: {subject}"
