"""Tailor the CV for one job: analyse, edit truthfully, fit to one page, write a report."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .config import Settings
from .cv import CV, fit_to_pages
from .models import Job
from .sources import linkedin, reed
from .sources.http import get_text
from .text import html_to_text
from .truth import violations


@dataclass
class Outcome:
    job: Job
    folder: Path
    docx: Path
    pdf: Path
    pages: int
    fit_score: int
    coverage_before: float
    coverage_after: float
    analysis: llm.Tailoring
    changed: list[tuple[str, str, str]] = field(default_factory=list)  # (id, before, after)
    rejected_edits: list[tuple[str, list[str]]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def ensure_full_description(job: Job) -> Job:
    """Aggregator results only carry a snippet; fetch the full advert when we can."""
    if not job.extra.get("snippet_only"):
        return job
    try:
        if job.source == "linkedin":
            return linkedin.full_details(job)
        if job.source == "reed" and os.environ.get("REED_API_KEY") and job.extra.get("reed_id"):
            full = reed.full_description(job.extra["reed_id"], os.environ["REED_API_KEY"])
        else:
            full = html_to_text(get_text(job.url))
        if len(full) > len(job.description) + 200:
            job.description = full[:20000]
            job.extra["snippet_only"] = False
    except Exception:
        pass  # keep the snippet; the report flags it
    return job


def _present(term: str, text: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I))


def coverage(keywords: list[llm.Keyword], text: str) -> float:
    if not keywords:
        return 0.0
    return round(100 * sum(_present(k.term, text) for k in keywords) / len(keywords), 1)


def tailor_job(job: Job, settings: Settings, out_root: Path, client: llm.LLM | None = None) -> Outcome:
    job = ensure_full_description(job)
    cv = CV(settings.cv_path)
    master = cv.full_text()
    client = client or llm.LLM(settings.provider)
    job_text = f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n{job.description}"
    t = llm.tailor(client, settings.model, job_text, cv.outline(), settings.extra_skills, settings.candidate_facts())

    changed, rejected = [], []

    def apply(bid: str, text: str) -> None:
        b = cv.block(bid)
        if b is None or not text.strip() or text.strip() == b.text.strip():
            return
        bad = violations(text, master, settings.extra_skills)
        if bad:
            rejected.append((bid, bad))
            return
        before = b.text
        cv.set_block_text(bid, text)
        changed.append((bid, before, cv.block(bid).text))

    if t.summary:
        apply("S1", t.summary)
    for e in t.bullet_edits:
        if e.id.startswith("B"):
            apply(e.id, e.text)
    for e in t.skills_edits:
        if e.id.startswith("K"):
            apply(e.id, e.text)
    cv.reorder_bullets([i for i in t.bullet_order if i.startswith("B")])

    folder = out_root / f"{job.id}-{slug(job.company)}-{slug(job.title)}"
    folder.mkdir(parents=True, exist_ok=True)
    name = slug(settings.profile.get("name", "cv")).replace("-", "_") or "cv"
    docx_path = folder / f"{name}_cv.docx"
    drop = [i for i in t.drop_order if i[:1] in {"B", "X"}]
    pdf, pages, dropped = fit_to_pages(cv, docx_path, settings.max_pages, drop)

    final_text = CV(docx_path).full_text()
    out = Outcome(
        job=job, folder=folder, docx=docx_path, pdf=pdf, pages=pages, fit_score=t.fit_score,
        coverage_before=coverage(t.keywords, master), coverage_after=coverage(t.keywords, final_text),
        analysis=t, changed=changed, rejected_edits=rejected, dropped=dropped,
    )
    (folder / "job.json").write_text(json.dumps(job.to_dict(), indent=2, default=str))
    (folder / "analysis.json").write_text(t.model_dump_json(indent=2))
    (folder / "report.md").write_text(report(out, CV(settings.cv_path)))
    return out


def report(o: Outcome, original: CV) -> str:
    t, j = o.analysis, o.job
    lines = [
        f"# {j.title} at {j.company}",
        "",
        f"- Location: {j.location}",
        f"- Link: {j.url}",
        f"- Posted: {j.posted_at.date() if j.posted_at else 'unknown'}",
        f"- Salary: {_salary(j)}",
        f"- Apply method: {j.apply_method}",
        f"- Fit score: **{t.fit_score}/100**. {t.fit_summary}",
        f"- ATS keyword coverage: {o.coverage_before}% before, **{o.coverage_after}% after**",
        f"- CV length: {o.pages} page(s)",
    ]
    if j.extra.get("snippet_only"):
        lines.append("- Note: only a snippet of the advert was available, so keywords may be incomplete.")
    if t.red_flags:
        lines += ["", "## Deal-breakers", *[f"- {f}" for f in t.red_flags]]
    if t.concerns:
        lines += ["", "## Things a recruiter may question", *[f"- {f}" for f in t.concerns]]
    lines += ["", "## Keywords", "", "| Keyword | Must-have | In your CV | Evidence | In tailored CV |", "|---|---|---|---|---|"]
    final = CV(o.docx).full_text()
    for k in t.keywords:
        lines.append(f"| {k.term} | {'yes' if k.must_have else 'no'} | {k.status} | {k.cv_evidence or '-'} | "
                     f"{'yes' if _present(k.term, final) else 'no'} |")
    gaps = [k.term for k in t.keywords if k.status == "missing"]
    if gaps:
        lines += ["", f"**Gaps (not added, because they're not on your CV):** {', '.join(gaps)}"]
    lines += ["", "## Changes"]
    for bid, before, after in o.changed:
        note = " (later removed to fit the page)" if bid in o.dropped else ""
        lines += ["", f"**{bid}**{note}", f"- Before: {before}", f"- After: {after}"]
    if not o.changed:
        lines.append("No wording changes were needed.")
    if o.rejected_edits:
        lines += ["", "## Edits blocked by the truthfulness check"]
        for bid, why in o.rejected_edits:
            lines.append(f"- {bid}: {'; '.join(why)}")
    if o.dropped:
        lines += ["", "## Removed to fit the page limit"]
        for bid in o.dropped:
            b = original.block(bid)
            lines.append(f"- {bid}: {b.text if b else ''}")
    return "\n".join(lines) + "\n"


def _salary(j: Job) -> str:
    if j.salary_min and j.salary_max:
        return f"£{int(j.salary_min):,} - £{int(j.salary_max):,}"
    if j.salary_max or j.salary_min:
        return f"£{int(j.salary_max or j.salary_min):,}"
    return "not listed"
