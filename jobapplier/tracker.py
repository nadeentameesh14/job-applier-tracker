"""Application tracker (a CSV that opens in Excel / Google Sheets) and the apply queue."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .config import Settings
from .models import Job

COLUMNS = [
    "job_id", "date_found", "date_applied", "company", "title", "location", "source", "link",
    "apply_method", "fit_score", "coverage_after", "missing_keywords", "salary_listed",
    "salary_answer", "status", "cv_file", "notes",
]

# Status values, in the order a job moves through them.
FOUND, TAILORED, AWAITING_APPROVAL, READY_AUTO, APPLIED, INTERVIEW, OFFER, REJECTED, SKIPPED = (
    "Found", "Tailored", "Awaiting approval", "Ready to auto-apply", "Applied", "Interview", "Offer", "Rejected", "Skipped"
)


class Tracker:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.rows: dict[str, dict[str, str]] = {}
        if self.path.exists():
            with self.path.open(newline="") as f:
                for r in csv.DictReader(f):
                    self.rows[r["job_id"]] = r

    def seen_keys(self) -> set[str]:
        return {f"{r['company'].strip().lower()}|{r['title'].strip().lower()}" for r in self.rows.values()}

    def upsert(self, job: Job, **fields) -> dict[str, str]:
        row = self.rows.get(job.id) or {c: "" for c in COLUMNS}
        row.update({
            "job_id": job.id, "company": job.company, "title": job.title, "location": job.location,
            "source": job.source, "link": job.url, "apply_method": job.apply_method,
        })
        row["date_found"] = row["date_found"] or date.today().isoformat()
        if job.salary_min or job.salary_max:
            row["salary_listed"] = f"{int(job.salary_min or job.salary_max)}-{int(job.salary_max or job.salary_min)}"
        for k, v in fields.items():
            row[k] = "" if v is None else str(v)
        self.rows[job.id] = row
        return row

    def count(self, status: str, method: str | None = None, on: str | None = None) -> int:
        return sum(1 for r in self.rows.values() if r["status"] == status
                   and (method is None or r["apply_method"] == method)
                   and (on is None or r["date_found"] == on))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self.rows.values(), key=lambda r: (r["date_found"], r["company"]), reverse=True)
        with self.path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def salary_answer(job: Job, settings: Settings) -> int:
    """Middle of the advertised range when there is one, else the default from settings."""
    lo, hi = job.salary_min, job.salary_max
    if lo and hi and not job.extra.get("salary_is_predicted"):
        return int(round((lo + hi) / 2, -3))
    return int(settings.answers.get("expected_salary") or 0)


def queue_status(job: Job) -> str:
    return READY_AUTO if job.apply_method == "auto" else AWAITING_APPROVAL
