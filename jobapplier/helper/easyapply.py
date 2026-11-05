"""Submit one LinkedIn Easy Apply application in your own browser, signed in as you.

It works like a careful person: opens the job, clicks Easy Apply, uploads the tailored CV, fills each
question from your settings (or asks Claude when the answer is on your CV), and clicks through to Submit.
If it meets a question it can't answer truthfully, it stops and leaves the tab open for you.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import answers as A

MODAL = "dialog[open], [data-testid=dialog], div.jobs-easy-apply-modal, div[data-test-modal], div.artdeco-modal, [role=dialog], [aria-modal=true]"
DEBUG_DIR = Path.home() / ".job-applier" / "debug"


def find_modal(page, timeout: float = 20):
    """The Easy Apply window. LinkedIn renders it in several ways (classic modal, a dialog inside a
    shadow root, or a separate apply page), so look for any visible dialog that holds a form or an
    apply button, in the page and its frames, and wait for it to appear."""
    end = time.time() + timeout
    while time.time() < end:
        for fr in [page.main_frame, *page.frames]:
            try:
                cands = fr.locator(MODAL)
                for i in range(min(cands.count(), 10)):
                    c = cands.nth(i)
                    if not c.is_visible():
                        continue
                    if c.locator("input, select, textarea, button").count():
                        txt = (c.inner_text() or "").lower()
                        if any(w in txt for w in ("apply", "contact info", "resume", "next", "review", "submit")):
                            return c
            except Exception:
                continue
        # newer layout: the apply flow is the page itself (url ends in /apply/)
        if "/apply" in page.url and page.locator("form").count():
            return page.locator("form").first.locator("xpath=..")
        time.sleep(1)
    return None


def dump_debug(page, name: str) -> str:
    """Save a screenshot, the page's HTML (including shadow roots and frames) and a few counts, so a
    problem with LinkedIn's page can be fixed. Never fails: errors are written into the file."""
    import json as _json
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    base = str(DEBUG_DIR / re.sub(r"[^A-Za-z0-9_-]+", "_", name)[:60])
    out: list[str] = [f"URL: {page.url}"]
    try:
        page.screenshot(path=base + ".png", full_page=False)
    except Exception as e:
        out.append(f"screenshot failed: {e}")
    for fr in page.frames:
        try:
            info = {"frame": fr.url[:200], "dialogs": fr.locator(MODAL).count(),
                    "inputs": fr.locator("input, select, textarea").count(),
                    "next_buttons": fr.get_by_role("button", name=re.compile("next|review|submit", re.I)).count(),
                    "apply_to_text": fr.get_by_text(re.compile(r"^Apply to ", re.I)).count()}
            out.append(_json.dumps(info))
        except Exception as e:
            out.append(f"frame {fr.url[:100]}: {e}")
    try:
        html = page.evaluate(r"""() => {
            const ser = n => { let h = n.outerHTML || n.innerHTML || '';
                n.querySelectorAll('*').forEach(e => { if (e.shadowRoot) h += '\n<!--SHADOW of ' + e.tagName + '-->\n' + ser(e.shadowRoot); });
                return h; };
            return ser(document.documentElement);
        }""")
        out.append(html)
    except Exception as e:
        out.append(f"page html failed: {e}")
        try:
            out.append(page.content())
        except Exception as e2:
            out.append(f"page content failed: {e2}")
    try:  # the browser's own view of the page, which also sees closed shadow roots
        cdp = page.context.new_cdp_session(page)
        doc = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})
        Path(base + "_dom.json").write_text(_json.dumps(doc))
        ax = cdp.send("Accessibility.getFullAXTree")
        Path(base + "_ax.json").write_text(_json.dumps(ax))
    except Exception as e:
        out.append(f"cdp dump failed: {e}")
    Path(base + ".html").write_text("\n".join(out), encoding="utf-8")
    return base + ".html"


@dataclass
class Result:
    status: str  # applied | needs_you | not_easy_apply | already_applied | error
    detail: str = ""


def pause(lo: float = 0.8, hi: float = 2.0) -> None:
    time.sleep(random.uniform(lo, hi))


def _label_for(field) -> str:
    try:
        txt = field.evaluate(
            """el => {
                if (el.labels && el.labels.length) return el.labels[0].innerText;
                const root = el.getRootNode ? el.getRootNode() : document;  // works inside shadow roots too
                const id = el.id && root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (id) return id.innerText;
                const fs = el.closest('fieldset'); if (fs) { const l = fs.querySelector('legend'); if (l) return l.innerText; }
                const g = el.closest('.jobs-easy-apply-form-element, .fb-dash-form-element, div');
                const l = g && g.querySelector('label, span.t-bold'); return l ? l.innerText : (el.getAttribute('aria-label') || '');
            }"""
        )
    except Exception:
        txt = ""
    return " ".join((txt or "").split())


def _group_question(fs) -> str:
    """The question for a group of radio buttons: its legend, the radios' aria-label (LinkedIn's
    newer form), or the text just before the group."""
    try:
        txt = fs.evaluate("""fs => {
            const lg = fs.querySelector('legend, span.fb-dash-form-element__label');
            if (lg && lg.innerText.trim()) return lg.innerText;
            const r = fs.querySelector('input[type=radio][aria-label]');
            if (r) return r.getAttribute('aria-label');
            let p = fs.previousElementSibling;
            while (p && !p.innerText.trim()) p = p.previousElementSibling;
            return p ? p.innerText : '';
        }""")
    except Exception:
        txt = ""
    return " ".join((txt or "").replace("*", " ").split())


def _option_text(radio) -> str:
    """The visible text of one radio option (its label, or the nearest text next to it)."""
    try:
        txt = radio.evaluate("""r => {
            if (r.labels && r.labels.length && r.labels[0].innerText.trim()) return r.labels[0].innerText;
            let n = r.parentElement;
            while (n && !n.innerText.trim() && n.tagName !== 'FIELDSET') n = n.parentElement;
            return n && n.tagName !== 'FIELDSET' ? n.innerText : (r.value || '');
        }""")
    except Exception:
        txt = ""
    return " ".join((txt or "").split())


def _fill_step(modal, ctx: dict) -> list[str]:
    """Fill every empty field in the current step. Returns labels it couldn't answer."""
    unknown: list[str] = []

    def answer(label: str, options: list[str] | None = None) -> str | None:
        v = A.lookup(label, ctx["profile"], {**ctx["answers"], "job_title": ctx.get("job_title", "")})
        if v == "__visa__":
            # a free-text box gets a true answer that doesn't give the date; a yes/no choice waits for you
            return None if options else A.VISA_TEXT
        if v and options:
            v = A.pick_option(v, options)
        if v is None:
            v = A.ask_claude(label, options or [], ctx["cv_text"], ctx["profile"], ctx["answers"], ctx["job"] + ("\n" + ctx["job_description"][:4000] if ctx.get("job_description") else ""))
        return v

    # CV upload: always attach the tailored PDF.
    for up in modal.locator("input[type=file]").all():
        try:
            up.set_input_files(ctx["cv_pdf"])
            pause()
        except Exception:
            pass

    for el in modal.locator("input[type=text], input[type=tel], input[type=email], input[type=number], textarea").all():
        try:
            if not el.is_visible() or (el.input_value() or "").strip():
                continue
            label = _label_for(el)
            v = answer(label)
            if v is None:
                unknown.append(label or "a text box")
                continue
            el.fill(str(v))
            pause(0.3, 0.8)
            # typeahead fields (e.g. city) need a pick from the list
            opt = modal.page.locator("[role=listbox] [role=option]").first
            if opt.count() and opt.is_visible():
                opt.click()
        except Exception:
            continue

    for sel in modal.locator("select").all():
        try:
            if not sel.is_visible():
                continue
            current = sel.evaluate("s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text : ''")
            want = (ctx["profile"].get("email") or "").strip().lower()
            if want and re.search(r"e-?mail", _label_for(sel), re.I):
                # always use the email address from your settings
                match = [o for o in sel.locator("option").all_inner_texts() if o.strip().lower() == want]
                if match and current.strip().lower() != want:
                    sel.select_option(label=match[0])
                    pause(0.3, 0.8)
                continue
            if current and not re.search(r"select an option", current, re.I):
                continue
            opts = [o.strip() for o in sel.locator("option").all_inner_texts() if o.strip()]
            opts = [o for o in opts if not re.search(r"select an option", o, re.I)]
            label = _label_for(sel)
            v = answer(label, opts)
            if v is None:
                unknown.append(label or "a drop-down")
                continue
            sel.select_option(label=v)
            pause(0.3, 0.8)
        except Exception:
            continue

    for fs in modal.locator("fieldset").all():
        try:
            radios = fs.locator("input[type=radio]")
            if not radios.count() or fs.locator("input[type=radio]:checked").count():
                continue
            label = _group_question(fs)
            opts = [_option_text(r) for r in radios.all()]
            v = answer(label, [o for o in opts if o])
            if v is None:
                unknown.append(label or "a choice")
                continue
            idx = next((k for k, o in enumerate(opts) if o.lower() == str(v).lower()), None)
            if idx is None:
                idx = next((k for k, o in enumerate(opts) if str(v).lower() in o.lower()), None)
            if idx is None:
                unknown.append(label or "a choice")
                continue
            r = radios.nth(idx)
            try:
                r.check(force=True, timeout=5000)
            except Exception:
                r.evaluate("e => (e.labels && e.labels[0] ? e.labels[0] : e).click()")
            pause(0.3, 0.8)
        except Exception:
            continue
    return unknown


def apply(page, job_url: str, cv_pdf: Path, ctx: dict, submit: bool = True) -> Result:
    page.goto(job_url, wait_until="domcontentloaded")
    pause(2, 4)
    if page.get_by_text(re.compile(r"Applied \d+ \w+ ago|Application submitted", re.I)).count():
        return Result("already_applied")
    btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply'), a:has-text('Easy Apply')").first
    try:
        btn.wait_for(state="visible", timeout=10_000)
    except Exception:
        pass
    if not btn.count() or "easy apply" not in (btn.inner_text() or "").lower():
        return Result("not_easy_apply", "No Easy Apply button (the job may apply on the company site or be closed)")
    btn.click()
    pause(1.5, 3)
    ctx = {**ctx, "cv_pdf": str(cv_pdf)}
    for step in range(12):
        modal = find_modal(page, timeout=20 if step == 0 else 8)
        if modal is None:
            f = dump_debug(page, f"{job_url.rstrip('/').split('/')[-1]}_step{step}")
            return Result("error", f"Couldn't find the Easy Apply window (details saved to {f})")
        follow = modal.locator("input#follow-company-checkbox:checked")
        if follow.count():
            modal.locator("label[for=follow-company-checkbox]").click()
        unknown = _fill_step(modal, ctx)
        submit_btn = modal.get_by_role("button", name=re.compile(r"submit application|^submit$", re.I)).first
        if submit_btn.count() and submit_btn.is_visible():
            if not submit:
                return Result("needs_you", "Test mode: everything is filled in; review it and press Submit yourself")
            submit_btn.click()
            pause(2, 4)
            done = page.locator("button[aria-label='Dismiss'], button:has-text('Done')").first
            if done.count():
                done.click()
            return Result("applied")
        nxt = modal.get_by_role("button", name=re.compile(r"continue to next step|review your application|^next$|^review$|^continue$", re.I)).first
        if not nxt.count():
            f = dump_debug(page, f"{job_url.rstrip('/').split('/')[-1]}_nonext{step}")
            return Result("needs_you", f"Couldn't find the Next button (details saved to {f})")
        try:
            before = modal.inner_text()
        except Exception:
            before = ""
        nxt.click()
        pause(1.5, 3)
        errs = modal.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages], [id^=error-message], [role=alert]")
        stuck = any(x.is_visible() and x.inner_text().strip() for x in errs.all())
        if not stuck:  # LinkedIn's newer form shows errors differently: if the page didn't change, we're stuck
            try:
                after = find_modal(page, timeout=5)
                stuck = after is not None and after.inner_text() == before
            except Exception:
                pass
        if stuck:
            missing = "; ".join(u for u in unknown if u) or "a required question"
            why = f" ({A.last_problem})" if A.last_problem else ""
            return Result("needs_you", f"Couldn't answer: {missing}{why}")
    return Result("needs_you", "Too many steps; left open for you")
