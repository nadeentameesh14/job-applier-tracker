"""Command line: python -m jobapplier <find|tailor|queue|run> [options]"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from .config import load_settings
from .filters import apply_filters
from .models import Job
from . import tracker as T

DATA = Path("data")


def _jobs_file() -> Path:
    return DATA / "found.json"


def _load_found() -> dict[str, Job]:
    if not _jobs_file().exists():
        return {}
    return {d["id"]: Job.from_dict(d) for d in json.loads(_jobs_file().read_text())}


STATS: dict = {}  # numbers from today's run, for the morning email


def _save_stats() -> None:
    from datetime import datetime, timezone
    DATA.mkdir(exist_ok=True)
    STATS["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    (DATA / "last_run.json").write_text(json.dumps(STATS, indent=2, default=str))


def cmd_find(args, settings) -> list[Job]:
    from .sources import fetch_all

    trk = T.Tracker(DATA / "tracker.csv")
    raw, problems = fetch_all(settings)
    kept, rejected = apply_filters(raw, settings.search, trk.seen_keys())
    DATA.mkdir(exist_ok=True)
    _jobs_file().write_text(json.dumps([j.to_dict() for j in kept], indent=2, default=str))
    print(f"\nFetched {len(raw)} jobs, {len(kept)} match your settings.\n")
    for p in problems:
        print(f"  ! {p}")
    reasons: dict[str, int] = {}
    for _, r in rejected:
        key = r.split("'")[0].strip() if r.startswith("location") else r.split(" ")[0] if r.startswith("posted") else r
        reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        print("Skipped: " + ", ".join(f"{n} {k}" for k, n in sorted(reasons.items(), key=lambda x: -x[1])))
    from collections import Counter
    STATS.update(fetched=len(raw), matched=len(kept), filtered_out=dict(sorted(reasons.items(), key=lambda x: -x[1])),
                 by_source=dict(Counter(j.source for j in raw)), source_problems=problems)
    print()
    for j in kept[: args.limit]:
        posted = j.posted_at.date().isoformat() if j.posted_at else "?"
        sal = f"£{int(j.salary_max):,}" if j.salary_max else ""
        print(f"  {j.id}  {posted}  {j.company[:22]:22}  {j.title[:48]:48}  {j.location[:30]:30} {sal:>9}  [{j.apply_method}]")
    n = getattr(args, "details", 0)
    if n:
        from .tailor import ensure_full_description
        print(f"\nOpening the top {n} adverts to see how each one is applied to:")
        for j in kept[:n]:
            j = ensure_full_description(j)
            how = {True: "LinkedIn Easy Apply", False: "company site"}.get(j.extra.get("easy_apply"), "not shown")
            print(f"  {j.id}  {j.title[:40]:40}  {how:20}  [{j.apply_method}]  {len(j.description):>6} chars  "
                  f"{j.apply_url if j.apply_url != j.url else ''}")
    return kept


def _pick_job(args) -> Job:
    if args.jd_file:
        return Job(source="manual", title=args.title or "Role", company=args.company or "Company",
                   location=args.location or "", url=args.url or "", description=Path(args.jd_file).read_text())
    found = _load_found()
    if args.job and args.job in found:
        return found[args.job]
    if args.job:
        sys.exit(f"Job {args.job} not in {_jobs_file()}. Run `find` first or pass --jd-file.")
    if not found:
        sys.exit("No jobs found yet. Run `python -m jobapplier find` first.")
    return next(iter(found.values()))


def cmd_tailor(args, settings, job: Job | None = None, client=None):
    from .tailor import tailor_job

    job = job or _pick_job(args)
    print(f"Tailoring your CV for: {job.title} at {job.company} ...")
    out = tailor_job(job, settings, DATA / "applications", client)
    trk = T.Tracker(DATA / "tracker.csv")
    missing = ", ".join(k.term for k in out.analysis.keywords if k.status == "missing")
    status = T.TAILORED if out.fit_score >= settings.min_fit_score and not out.analysis.red_flags else T.SKIPPED
    trk.upsert(out.job, fit_score=out.fit_score, coverage_after=out.coverage_after, missing_keywords=missing,
               cv_file=str(out.pdf), status=status, salary_answer=T.salary_answer(out.job, settings),
               notes="; ".join(out.analysis.red_flags + out.analysis.concerns))
    trk.save()
    print((out.folder / "report.md").read_text())
    print(f"Files: {out.docx}\n       {out.pdf}")
    return out


def cmd_queue(args, settings):
    trk = T.Tracker(DATA / "tracker.csv")
    row = trk.rows.get(args.job)
    if not row:
        sys.exit(f"{args.job} is not in the tracker. Tailor it first.")
    found = _load_found()
    saved = Path(row["cv_file"]).parent / "job.json"  # has the full advert and how it's applied to
    job = Job.from_dict(json.loads(saved.read_text())) if saved.exists() else found.get(args.job)
    status = T.queue_status(job)
    answers = dict(settings.answers)
    answers["expected_salary"] = T.salary_answer(job, settings)
    folder = Path(row["cv_file"]).parent
    (folder / "application.json").write_text(json.dumps({
        "job_id": job.id, "apply_method": job.apply_method, "apply_url": job.apply_url or job.url,
        "cv_pdf": row["cv_file"], "answers": answers, "status": status, "queued_on": date.today().isoformat(),
    }, indent=2))
    trk.upsert(job, status=status)
    trk.save()
    print(f"Queued {job.title} at {job.company}: {status} ({job.apply_method}).")


def _log_score(path: Path, job: Job, sc, verdict: str) -> None:
    """Every job scored, with the reason, so the scoring can be checked (opens in Excel/Sheets)."""
    import csv
    from datetime import date

    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "score", "verdict", "company", "title", "location", "source", "apply_method",
                        "link", "reason", "deal_breakers", "concerns"])
        w.writerow([date.today().isoformat(), sc.fit_score, verdict, job.company, job.title, job.location, job.source,
                    job.apply_method, job.url, sc.reason, "; ".join(sc.red_flags), "; ".join(sc.concerns)])


def cmd_run(args, settings):
    """Daily run: find, tailor the best matches up to the caps, and queue them."""
    from datetime import datetime, timezone
    STATS["started_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    kept = cmd_find(args, settings)
    caps = {"linkedin": settings.apply.get("daily_cap_linkedin", 15), "auto": settings.apply.get("daily_cap_auto", 15),
            "manual": settings.apply.get("daily_cap_manual", settings.apply.get("daily_cap_linkedin", 15))}
    if getattr(args, "test", False):
        settings.max_screen = 15
        caps = {k: min(v, 1) for k, v in caps.items()}
        print("Test run: scoring up to 15 jobs, tailoring at most 1 per apply method.")
    done = {"linkedin": 0, "auto": 0, "manual": 0}
    from .cv import CV
    from .llm import LLM, AuthError, screen
    from .tailor import ensure_full_description

    client = LLM(settings.provider)
    cv_text = CV(settings.cv_path).full_text()
    screened = 0
    scores_path = DATA / "scores.csv"
    STATS.update(test=bool(getattr(args, "test", False)), screened=0, suited=0,
                 below_threshold=0, deal_breakers=0, over_cap=0, tailored=0, queued={"linkedin": 0, "auto": 0, "manual": 0},
                 not_screened=0, min_fit_score=settings.min_fit_score)
    for job in kept:
        if screened >= settings.max_screen:
            print(f"  Reached max_screen_per_run ({settings.max_screen}); the rest wait for tomorrow.")
            STATS["not_screened"] = len(kept) - screened
            break
        try:
            job = ensure_full_description(job)
            m = job.apply_method  # a LinkedIn job may turn out to apply on the company's own site
            screened += 1
            sc = screen(client, settings.screen_model,
                        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n{job.description}", cv_text,
                        settings.candidate_facts())
        except AuthError as e:
            print(f"  ! Stopping: {e}")
            STATS["stopped_early"] = str(e)
            _save_stats()
            raise SystemExit(1)
        except Exception as e:
            print(f"  ! could not screen {job.title} at {job.company}: {e}")
            continue
        passes = (sc.fit_score >= settings.min_fit_score or settings.always_apply(job.title)) and not sc.red_flags
        over_cap = passes and done[m] >= caps[m]
        STATS["screened"] += 1
        STATS["suited"] += int(passes)
        STATS["deal_breakers"] += int(bool(sc.red_flags))
        STATS["below_threshold"] += int(not sc.red_flags and sc.fit_score < settings.min_fit_score)
        STATS["over_cap"] += int(over_cap)
        verdict = "skip" if not passes else "over today's cap" if over_cap else "tailor"
        _log_score(scores_path, job, sc, verdict)
        if not passes:
            trk = T.Tracker(DATA / "tracker.csv")  # reload: tailor/queue steps write to it too
            trk.upsert(job, status=T.SKIPPED, fit_score=sc.fit_score, notes="; ".join([sc.reason, *sc.red_flags, *sc.concerns]))
            trk.save()
            print(f"  - skipped {job.title} at {job.company}: score {sc.fit_score}. {sc.reason}")
            continue
        if over_cap:
            print(f"  = {job.title} at {job.company}: score {sc.fit_score}, but today's {m} cap is full (kept for tomorrow)")
            continue
        try:
            out = cmd_tailor(args, settings, job, client)
        except Exception as e:
            print(f"  ! could not tailor {job.title} at {job.company}: {e}")
            continue
        STATS["tailored"] += 1
        if (out.fit_score >= settings.min_fit_score or settings.always_apply(job.title)) and not out.analysis.red_flags:
            args.job = job.id
            cmd_queue(args, settings)
            done[m] += 1
            STATS["queued"][m] += 1
    print(f"\nQueued today: {done}")
    _save_stats()


def cmd_digest(args, settings):
    from .digest import send
    if not settings.digest.get("enabled", True) and not args.preview:
        print("The morning email is turned off (digest.enabled: false).")
        return
    tail = Path(args.log).read_text()[-4000:] if args.log and Path(args.log).exists() else ""
    print(send(settings, tail, dry_run=args.preview))


def cmd_sheet(args, settings):
    from .sheet import sync
    print(sync())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jobapplier")
    ap.add_argument("--settings", default="settings.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find", help="search all sources and list matching jobs")
    f.add_argument("--limit", type=int, default=30)
    f.add_argument("--details", type=int, default=5, help="open this many top adverts to check how they're applied to")
    t = sub.add_parser("tailor", help="tailor your CV for one job")
    t.add_argument("--job", help="job id from `find`")
    t.add_argument("--jd-file", help="or a text file with a job description")
    t.add_argument("--title"); t.add_argument("--company"); t.add_argument("--location"); t.add_argument("--url")
    q = sub.add_parser("queue", help="add a tailored job to the apply queue")
    q.add_argument("--job", required=True)
    r = sub.add_parser("run", help="find + tailor + queue, up to the daily caps")
    r.add_argument("--limit", type=int, default=30)
    r.add_argument("--jd-file", default=None); r.add_argument("--job", default=None)
    r.add_argument("--test", action="store_true", help="small test run: score 15 jobs, tailor and queue at most 2")
    d = sub.add_parser("digest", help="send the morning summary email")
    d.add_argument("--preview", action="store_true", help="write data/digest_preview.html instead of sending")
    d.add_argument("--log", default="", help="run log to quote if the run failed")
    sub.add_parser("sheet", help="copy the tracker into your Google Sheet")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    settings = load_settings(args.settings)
    {"find": cmd_find, "tailor": cmd_tailor, "queue": cmd_queue, "run": cmd_run, "digest": cmd_digest,
     "sheet": cmd_sheet}[args.cmd](args, settings)


if __name__ == "__main__":
    main()
