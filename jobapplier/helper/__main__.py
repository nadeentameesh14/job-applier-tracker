"""Laptop helper: approve today's LinkedIn Easy Apply batch with one click, then it applies for you.

    python -m jobapplier.helper            # sync, show the approval page, apply to what you approve
    python -m jobapplier.helper --test     # fill everything but stop before Submit (try this first)
    python -m jobapplier.helper --login    # just open the browser so you can sign in to LinkedIn once

It uses its own browser profile (in ~/.job-applier/browser), signed in to LinkedIn as you. Your
password is never stored by this tool; LinkedIn keeps you signed in like any browser does.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import subprocess
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from ..config import load_settings
from ..cv import CV
from .. import tracker as T

PROFILE_DIR = Path.home() / ".job-applier" / "browser"
PORT = 8765
TEST_MODE = False


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def load_queue(repo: Path) -> list[dict]:
    """Easy Apply jobs waiting for approval, best fit first."""
    trk = {}
    p = repo / "data" / "tracker.csv"
    if p.exists():
        trk = {r["job_id"]: r for r in csv.DictReader(p.open(newline=""))}
    items = []
    for f in sorted((repo / "data" / "applications").glob("*/application.json")):
        a = json.loads(f.read_text())
        ok = {T.AWAITING_APPROVAL, "Needs you"} if TEST_MODE else {T.AWAITING_APPROVAL}  # a test can retry ones that got stuck
        if a.get("apply_method") != "linkedin" or a.get("status") not in ok:
            continue
        job = json.loads((f.parent / "job.json").read_text()) if (f.parent / "job.json").exists() else {}
        row = trk.get(a["job_id"], {})
        items.append({**a, "folder": str(f.parent), "title": job.get("title", row.get("title", "")),
                      "company": job.get("company", row.get("company", "")), "location": job.get("location", ""),
                      "url": job.get("url", a.get("apply_url", "")), "fit": row.get("fit_score", ""),
                      "report": str(f.parent / "report.md")})
    return sorted(items, key=lambda x: -int(x["fit"] or 0))


def load_career(repo: Path) -> list[dict]:
    """Jobs to apply for on company sites without asking: career-site jobs, plus LinkedIn jobs that apply
    off LinkedIn (their real apply link is found while you're signed in). Best fit first."""
    trk = {}
    p = repo / "data" / "tracker.csv"
    if p.exists():
        trk = {r["job_id"]: r for r in csv.DictReader(p.open(newline=""))}
    items = []
    for f in sorted((repo / "data" / "applications").glob("*/application.json")):
        a = json.loads(f.read_text())
        job = json.loads((f.parent / "job.json").read_text()) if (f.parent / "job.json").exists() else {}
        url = job.get("url", a.get("apply_url", ""))
        st = a.get("status")
        retry = TEST_MODE and st == "Needs you"
        if a.get("apply_method") == "auto" and (st == T.READY_AUTO or retry):
            pass
        elif a.get("apply_method") == "manual" and "linkedin.com" in url and (st == T.AWAITING_APPROVAL or retry):
            pass
        else:
            continue
        row = trk.get(a["job_id"], {})
        items.append({**a, "folder": str(f.parent), "title": job.get("title", row.get("title", "")),
                      "company": job.get("company", row.get("company", "")), "location": job.get("location", ""),
                      "url": url, "fit": row.get("fit_score", ""), "description": job.get("description", "")})
    return sorted(items, key=lambda x: -int(x["fit"] or 0))


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Approve today's applications</title>
<style>body{{font:15px system-ui;max-width:760px;margin:24px auto;padding:0 16px;color:#222}}
li{{margin:10px 0;list-style:none}} .s{{color:#666;font-size:13px}} button{{font-size:16px;padding:10px 18px}}</style>
<h2>Today's LinkedIn Easy Apply batch ({n})</h2>
<p>Untick anything you don't want. Then press <b>Approve and apply</b> and leave the browser window alone
while it works (about a minute per job).</p>
<form method=post action=/approve><ul>{rows}</ul>
<button type=submit>Approve and apply</button> &nbsp; <button type=submit formaction=/skip>Not today</button></form>"""


def approval_page(items: list[dict]):
    """Show the batch on a local web page. Returns a function that waits for your answer and gives the
    approved job ids (None if skipped)."""
    rows = "".join(
        f"<li><label><input type=checkbox name=id value='{html.escape(i['job_id'])}' checked> "
        f"<b>{html.escape(i['title'])}</b> at {html.escape(i['company'])} "
        f"<span class=s>({html.escape(i['location'])}, fit {html.escape(str(i['fit']))}) "
        f"<a href='{html.escape(i['url'])}' target=_blank>advert</a> · "
        f"<a href='file://{html.escape(i['folder'])}' target=_blank>CV and report</a></span></label></li>"
        for i in items)
    body = PAGE.format(n=len(items), rows=rows).encode()
    result: dict = {}
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            ids = parse_qs(self.rfile.read(n).decode()).get("id", [])
            result["ids"] = None if self.path == "/skip" else ids
            msg = "Skipped for today." if self.path == "/skip" else f"Approved {len(ids)}. Applying now; you can close this tab."
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(f"<p style='font:16px system-ui;margin:40px'>{msg}</p>".encode())
            done.set()

    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    webbrowser.open(f"http://127.0.0.1:{PORT}/")
    print(f"Approval page: http://127.0.0.1:{PORT}/ (open in your browser; career-site applications carry on meanwhile)")

    def wait() -> list[str] | None:
        done.wait()
        srv.shutdown()
        return result.get("ids")
    return wait


def browser(pw):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # no fixed viewport: the page fills the real window, which opens maximised
    kw = dict(user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True, args=["--start-maximized", "--window-position=0,0", "--window-size=1440,900"])
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **kw)  # your installed Chrome
    except Exception:
        ctx = pw.chromium.launch_persistent_context(**kw)
    # LinkedIn may draw the Easy Apply window inside a "closed" shadow root, which automation can't
    # see into. Make every shadow root open so the helper can read the form like you can.
    ctx.add_init_script("""(() => { const o = Element.prototype.attachShadow;
        Element.prototype.attachShadow = function (init) { return o.call(this, Object.assign({}, init, {mode: 'open'})); }; })();""")
    return ctx


def ensure_signed_in(page) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    if "/feed" in page.url:
        return True
    print("Please sign in to LinkedIn in the window that just opened (I'll wait up to 5 minutes).")
    try:
        page.wait_for_url("**/feed/**", timeout=300_000)
        return True
    except Exception:
        return False


def wait_for_you(ctx, message: str) -> None:
    """Keep the browser open until you're done: Enter in Terminal, or closing the browser window
    (when the helper was started automatically there's no Terminal to press Enter in)."""
    print(message)
    if sys.stdin and sys.stdin.isatty():
        try:
            input()
            return
        except EOFError:
            pass
    try:
        ctx.wait_for_event("close", timeout=6 * 3600 * 1000)
    except Exception:
        pass


def notify(title: str, message: str, popup: bool = True) -> None:
    """Get your attention on a Mac: a sound, a notification, and (by default) a pop-up window that stays
    until you press OK. Banner notifications alone can be hidden by Focus or notification settings."""
    if sys.platform != "darwin":
        return
    q = lambda t: t.replace("\\", "\\\\").replace('"', '\\"')[:220]
    try:
        subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
    except Exception:
        pass
    try:
        subprocess.run(["osascript", "-e", f'display notification "{q(message)}" with title "{q(title)}" sound name "Glass"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    if popup:
        try:  # runs in the background so the helper carries on with the next job
            subprocess.Popen(["osascript", "-e",
                              f'display alert "{q(title)}" message "{q(message)}" buttons {{"OK"}} giving up after 3600'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def mark(repo: Path, item: dict, status: str, detail: str = "", extra: dict | None = None) -> None:
    if TEST_MODE:  # a test run never changes the tracker, so the same jobs can be tried again
        return
    f = Path(item["folder"]) / "application.json"
    a = json.loads(f.read_text())
    a["status"], a["detail"] = status, detail
    a.update(extra or {})
    if status == T.APPLIED:
        a["applied_on"] = date.today().isoformat()
    f.write_text(json.dumps(a, indent=2))
    p = repo / "data" / "tracker.csv"
    if p.exists():
        rows = list(csv.DictReader(p.open(newline="")))
        for r in rows:
            if r["job_id"] == item["job_id"]:
                r["status"] = status
                if status == T.APPLIED:
                    r["date_applied"] = date.today().isoformat()
                if detail:
                    r["notes"] = (detail + "; " + r.get("notes", "")).strip("; ")
        with p.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=T.COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jobapplier.helper")
    ap.add_argument("--repo", default=".", help="your private repo folder")
    ap.add_argument("--test", action="store_true", help="fill in everything but don't press Submit")
    ap.add_argument("--no-restart", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--diagnose", metavar="JOB_URL", help="open one job, click Easy Apply and save what the page looks like")
    ap.add_argument("--ask", action="append", default=[], metavar="WORDS",
                    help="always stop and ask you at questions containing these words (can repeat)")
    ap.add_argument("--ping", action="store_true", help="just show a test notification")
    ap.add_argument("--try", dest="try_url", metavar="JOB_URL",
                    help="safe test on one job link (LinkedIn or a career site): fills the form, never submits")
    ap.add_argument("--login", action="store_true", help="open the browser to sign in to LinkedIn, then exit")
    # unknown options are allowed until after the update below, so a newer option works on first use
    args, unknown_opts = ap.parse_known_args(argv)
    if unknown_opts and "--no-restart" in sys.argv:
        ap.error("unrecognized arguments: " + " ".join(unknown_opts))
    repo = Path(args.repo).resolve()
    global TEST_MODE
    TEST_MODE = args.test

    if args.ping:
        notify("Job helper needs you: Test Company", "This is what a ping looks like. The application tab stays open for you.")
        print("Sent a test ping: you should hear a sound and see a pop-up window (press OK to close it).")
        return

    from playwright.sync_api import sync_playwright

    if args.diagnose:
        from .easyapply import dump_debug, find_modal
        with sync_playwright() as pw:
            ctx = browser(pw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(args.diagnose, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            dump_debug(page, "diag_before")
            page.locator("button.jobs-apply-button, button:has-text('Easy Apply'), a:has-text('Easy Apply')").first.click()
            page.wait_for_timeout(6000)
            print("Found the window:", find_modal(page, timeout=5) is not None)
            print("Saved:", dump_debug(page, "diag_after"))
            ctx.close()
        return

    if args.login:
        with sync_playwright() as pw:
            ctx = browser(pw)
            ok = ensure_signed_in(ctx.pages[0] if ctx.pages else ctx.new_page())
            print("Signed in. You can close the window." if ok else "Not signed in.")
            ctx.close()
        return

    print("Getting today's queue from GitHub...")
    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    pulled = git(repo, "pull", "--rebase", "--autostash")
    if pulled.returncode:
        print("  (couldn't pull: " + (pulled.stderr.strip()[-200:] or "unknown") + ")")
    elif git(repo, "diff", "--quiet", before, "HEAD", "--", "jobapplier").returncode and "--no-restart" not in sys.argv:
        print("  (the helper itself was updated; restarting with the new version)")
        import os
        os.execv(sys.executable, [sys.executable, "-m", "jobapplier.helper", *sys.argv[1:], "--no-restart"])
    settings = load_settings(repo / "settings.yaml")
    if args.try_url:
        return try_one(repo, settings, args)
    items = load_queue(repo)[: settings.apply.get("daily_cap_linkedin", 15)]
    career = load_career(repo)[: settings.apply.get("daily_cap_auto", 15)
                               + settings.apply.get("daily_cap_manual", settings.apply.get("daily_cap_linkedin", 15))]
    if not items and not career:
        print("Nothing to do today.")
        return

    from .answers import find_claude
    from . import careersite as CS
    from .easyapply import apply

    if not find_claude():
        print("Note: Claude Code isn't installed here, so I can only answer questions covered by your settings.\n"
              "  To fix: run  bash helper/install_mac.sh  again (it installs Claude Code and asks you to sign in).")
    wait = approval_page(items) if items else None

    cv_text = CV(settings.cv_path).full_text()
    always_ask = list(settings.apply.get("always_ask") or []) + args.ask
    counts = {"applied": 0, "needs_you": 0}
    done_items: list[dict] = []

    def ctx_for(i: dict) -> dict:
        desc = i.get("description", "")
        if not desc:
            try:
                desc = json.loads((Path(i["folder"]) / "job.json").read_text()).get("description", "")
            except Exception:
                pass
        return {"profile": settings.profile, "cv_text": cv_text,
                "answers": {**settings.answers, **i.get("answers", {})},
                "job": f"{i['title']} at {i['company']}", "job_title": i["title"].removeprefix("TEST - "),
                "job_description": desc, "always_ask": always_ask}

    def pdf_for(i: dict) -> Path:
        return repo / i["cv_pdf"] if not Path(i["cv_pdf"]).is_absolute() else Path(i["cv_pdf"])

    def record(i: dict, res, page, extra: dict | None = None):
        """Update the tracker for one result; returns the page to use next."""
        print(res.status + (f": {res.detail}" if res.detail else ""))
        done_items.append(i)
        if res.status == "applied":
            mark(repo, i, T.APPLIED, "", extra)
            counts["applied"] += 1
        elif res.status == "already_applied":
            mark(repo, i, T.APPLIED, "Already applied", extra)
        elif res.status == "closed":
            mark(repo, i, T.SKIPPED, res.detail, extra)
        elif res.status == "not_easy_apply":
            mark(repo, i, "Apply on company site", res.detail, extra)
        else:
            mark(repo, i, "Needs you", res.detail, extra)
            counts["needs_you"] += 1
            if not args.test or "Test mode" not in res.detail:
                notify(f"Job helper needs you: {i['company']}", res.detail)
            if not args.test:
                return page.context.new_page()  # leave that tab open for you to finish
        return page

    with sync_playwright() as pw:
        ctx = browser(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        signed_in = ensure_signed_in(page)

        # 1) company career sites: no approval needed
        for i in career:
            print(f"- [career site] {i['title']} at {i['company']} ... ", end="", flush=True)
            extra = None
            try:
                url = i["url"]
                if "linkedin.com" in url:
                    if not signed_in:
                        print("skipped: not signed in to LinkedIn, so the apply link can't be found")
                        continue
                    dest = CS.resolve_linkedin(page, url)
                    if not dest:
                        page = record(i, type("R", (), {"status": "not_easy_apply", "detail": "Couldn't find the apply link"})(), page)
                        continue
                    extra = {"apply_url": dest}
                    if not CS.supported(dest):
                        page = record(i, type("R", (), {"status": "not_easy_apply",
                                                        "detail": f"Apply on the company site: {dest}"})(), page, extra)
                        continue
                    url = dest
                res = CS.apply(page, url, pdf_for(i), ctx_for(i), submit=not args.test)
            except Exception as e:
                res = type("R", (), {"status": "error", "detail": str(e)[:200]})()
            page = record(i, res, page, extra)

        if career and not args.test:  # save progress now, in case you approve the LinkedIn batch much later
            git(repo, "add", "-A", "data")
            git(repo, "commit", "-m", f"Laptop helper: career sites {date.today().isoformat()}")
            git(repo, "push")

        # 2) LinkedIn Easy Apply: only what you approved
        if wait:
            approved = wait()
            chosen = [i for i in items if i["job_id"] in set(approved or [])]
            for i in items:
                if i not in chosen:
                    mark(repo, i, T.SKIPPED, "Not approved")
            if chosen and not signed_in:
                signed_in = ensure_signed_in(page)
            for i in chosen if signed_in else []:
                print(f"- [Easy Apply] {i['title']} at {i['company']} ... ", end="", flush=True)
                try:
                    res = apply(page, i["url"], pdf_for(i), ctx_for(i), submit=not args.test)
                except Exception as e:
                    res = type("R", (), {"status": "error", "detail": str(e)[:200]})()
                page = record(i, res, page)
        if args.test:
            wait_for_you(ctx, "Test run finished. Look over the filled-in forms, then press Enter (or close the browser)...")
        elif counts["needs_you"]:
            wait_for_you(ctx, f"{counts['needs_you']} application(s) need you: their tabs are open in the browser. "
                              "Finish them, then press Enter here (or just close the browser)...")
        try:
            ctx.close()
        except Exception:
            pass

    if args.test:
        notify("Job helper test finished", f"{len(done_items)} filled in; nothing was submitted", popup=False)
        print("\nTest finished. Nothing was submitted and the tracker wasn't changed.")
        return
    applied = counts["applied"]
    git(repo, "add", "-A", "data")
    git(repo, "commit", "-m", f"Laptop helper: applied to {applied} on {date.today().isoformat()}")
    pushed = git(repo, "push")
    notify("Job helper finished", f"{applied} applied" + (f", {counts['needs_you']} needed you" if counts["needs_you"] else ""),
           popup=False)
    print(f"\nDone: {applied} applied." + ("" if pushed.returncode == 0 else " (Couldn't push the tracker update; it will go next time.)"))


def try_one(repo: Path, settings, args) -> None:
    """Fill in the application for one job link, exactly as a real run would, but never press Submit."""
    from playwright.sync_api import sync_playwright
    from . import careersite as CS
    from .easyapply import apply

    url = args.try_url.strip()
    pdfs = sorted((repo / "data" / "applications").glob("*/*_cv.pdf"), key=lambda p: p.stat().st_mtime)
    if not pdfs:
        print("No tailored CV found yet to upload; run the daily job first.")
        return
    ctx_d = {"profile": settings.profile, "cv_text": CV(settings.cv_path).full_text(), "answers": dict(settings.answers),
             "job": "this job", "job_title": "", "job_description": "",
             "always_ask": list(settings.apply.get("always_ask") or []) + args.ask}
    print(f"Trying {url} (test: nothing will be submitted; uploading {pdfs[-1].name} from your latest tailored CV)")
    with sync_playwright() as pw:
        ctx = browser(pw)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if "linkedin.com" in url and not ensure_signed_in(page):
            print("Not signed in to LinkedIn.")
            return
        try:  # read the advert so answers like "why do you want to join us?" know the company and role
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            ctx_d["job"] = page.title().replace("| LinkedIn", "").strip()
            body = page.locator("#job-details, .jobs-description, article, main").first
            ctx_d["job_description"] = (body.inner_text() if body.count() else page.locator("body").inner_text())[:4000]
            print(f"  Job: {ctx_d['job']}")
        except Exception:
            pass
        if "linkedin.com" in url:
            res = apply(page, url, pdfs[-1], ctx_d, submit=False)
            if res.status == "not_easy_apply":
                print("Not an Easy Apply job; finding where it applies...")
                dest = CS.resolve_linkedin(page, url)
                print(f"  It applies at: {dest or 'unknown'}")
                if dest and CS.supported(dest):
                    res = CS.apply(page, dest, pdfs[-1], ctx_d, submit=False)
                elif dest:
                    page.goto(dest)
                    res = type("R", (), {"status": "not supported", "detail": "That site isn't one the helper fills in yet"})()
        else:
            res = CS.apply(page, url, pdfs[-1], ctx_d, submit=False)
        print(f"Result: {res.status}" + (f": {res.detail}" if res.detail else ""))
        if res.status == "needs_you" and "Test mode" not in res.detail:
            notify("Job helper needs you (test)", res.detail)
        wait_for_you(ctx, "Look over the form in the browser, then press Enter here (or close the browser).")
        try:
            ctx.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
