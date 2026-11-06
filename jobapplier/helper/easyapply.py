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


def _is_typeahead(el) -> bool:
    try:
        return el.evaluate("""e => e.getAttribute('role') === 'combobox' || !!e.getAttribute('aria-autocomplete')
                                   || e.getAttribute('aria-haspopup') === 'listbox'""")
    except Exception:
        return False


def _fill_typeahead(el, value: str) -> bool:
    """Search boxes such as Location or Country only keep a value picked from their list, so type a short
    search ('London' for 'London, United Kingdom'), wait for the list, and pick the best match."""
    page = el.page
    parts = [p.strip() for p in value.split(",") if p.strip()]
    for query in dict.fromkeys([parts[0] if parts else value, value]):
        try:
            el.click()
            el.fill("")
            el.press_sequentially(query, delay=60)
        except Exception:
            return False
        opts = page.locator("[role=listbox] [role=option]:visible, [role=option]:visible")
        end = time.time() + 6
        while time.time() < end and not opts.count():
            time.sleep(0.5)
        n = min(opts.count(), 15)
        if not n:
            continue
        texts = []
        for k in range(n):
            try:
                texts.append(" ".join(opts.nth(k).inner_text().split()))
            except Exception:
                texts.append("")
        low = [t.lower() for t in texts]
        best = None
        for k, t in enumerate(low):  # e.g. "London, England, United Kingdom" for "London, United Kingdom"
            if all(p.lower() in t for p in parts):
                best = k
                break
        if best is None:
            for k, t in enumerate(low):
                if t.startswith(query.lower()) or query.lower() in t:
                    best = k
                    break
        if best is None:
            continue
        opts.nth(best).click()
        pause(0.5, 1)
        return True
    try:
        el.press("Escape")
    except Exception:
        pass
    return False


def _fill_step(modal, ctx: dict) -> list[str]:
    """Fill every empty field in the current step. Returns labels it couldn't answer."""
    unknown: list[str] = []

    def answer(label: str, options: list[str] | None = None) -> str | None:
        for pat in ctx.get("always_ask", []):  # questions you want to answer yourself
            if pat and re.search(pat, label, re.I):
                return None
        v = A.lookup(label, ctx["profile"], {**ctx["answers"], "job_title": ctx.get("job_title", "")})
        if v == "__visa__":
            # a free-text box gets a true answer that doesn't give the date; a yes/no choice waits for you
            return None if options else A.VISA_TEXT
        if v and "|" in v:  # several acceptable answers, best first ("Female|Woman", "Arab|Other")
            alts = [a.strip() for a in v.split("|") if a.strip()]
            v = next((p for p in (A.pick_option(a, options) for a in alts) if p), None) if options else alts[0]
        elif v and options:
            v = A.pick_option(v, options)
        if v is None:
            v = A.ask_claude(label, options or [], ctx["cv_text"], ctx["profile"], ctx["answers"], ctx["job"] + ("\n" + ctx["job_description"][:4000] if ctx.get("job_description") else ""))
        return v

    # CV upload: always attach the tailored PDF.
    uploaded = False
    for up in modal.locator("input[type=file]").all():
        try:
            what = " ".join([up.get_attribute("id") or "", up.get_attribute("name") or "", _label_for(up)]).lower()
            if "cover" in what:  # never put the CV in a cover-letter box
                continue
            if up.evaluate("e => e.files && e.files.length > 0"):
                continue
            up.set_input_files(ctx["cv_pdf"])
            uploaded = True
            pause()
        except Exception:
            pass
    if uploaded:  # career sites often read the CV and fill fields from it; let that finish first
        time.sleep(4)

    for el in modal.locator("input:not([type]), input[type=text], input[type=tel], input[type=email], input[type=url], input[type=number], textarea").all():
        try:
            if not el.is_visible() or (el.input_value() or "").strip():
                continue
            if el.evaluate("e => { const c = e.closest('[class*=select__control]'); return !!(c && c.querySelector('[class*=single-value], [class*=multi-value]')); }"):
                continue  # a search box that already shows its choice
            label = _label_for(el)
            v = answer(label)
            if v is None:
                unknown.append(label or "a text box")
                continue
            if _is_typeahead(el):
                if not _fill_typeahead(el, str(v)):
                    unknown.append(label or "a search box")
                continue
            el.fill(str(v))
            pause(0.3, 0.8)
            # some plain-looking fields still pop up a list to pick from
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
            placeholder = r"^(select|choose|please select|--|—)|select an option"
            has_value = sel.evaluate("s => !!(s.value && s.value.trim())")
            if current and has_value and not re.search(placeholder, current.strip(), re.I):
                continue
            opts = [o.strip() for o in sel.locator("option").all_inner_texts() if o.strip()]
            opts = [o for o in opts if not re.search(placeholder, o, re.I)]
            label = _label_for(sel)
            v = answer(label, opts)
            if v is None:
                unknown.append(label or "a drop-down")
                continue
            sel.select_option(label=v)
            pause(0.3, 0.8)
        except Exception:
            continue

    # tick consent boxes ("I agree to the privacy policy", "I confirm the above is accurate")
    for cb in modal.locator("input[type=checkbox]").all():
        try:
            if cb.is_checked():
                continue
            lab = _label_for(cb)
            if re.search(r"\b(agree|consent|acknowledge|privacy|terms|confirm|certify|accurate|accept)\b", lab, re.I) \
                    and not re.search(r"\b(marketing|newsletter|future (jobs|roles|opportunities)|follow)\b", lab, re.I):
                cb.check(force=True, timeout=5000)
                pause(0.2, 0.5)
        except Exception:
            continue

    for fs in modal.locator("fieldset").all():
        try:
            radios = fs.locator("input[type=radio]")
            if not radios.count():
                boxes = fs.locator("input[type=checkbox]")
                if boxes.count() > 1 and not fs.locator("input[type=checkbox]:checked").count():
                    radios = boxes  # a pick-one-or-more group: tick the best answer
            if not radios.count() or fs.locator("input[type=radio]:checked").count():
                continue
            if radios.first.get_attribute("type") == "checkbox" and fs.locator("input[type=checkbox]:checked").count():
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


EASY_NAME = re.compile(r"easy apply", re.I)
APPLY_ANY = re.compile(r"^\s*(easy )?apply\b|apply on (the )?company|apply to .{1,80}", re.I)


def _is_job_button(el) -> bool:
    """True for the job's own button, not a search filter or a link in the page's menus."""
    try:
        return el.evaluate("""e => {
            if (e.closest('nav, #global-nav, header.global-nav, [role=navigation], [role=search], .search-reusables__filters-bar, '
                          + '.jobs-search-box, [data-testid*=filter], [aria-label*=filter i]')) return false;
            const h = (e.getAttribute('href') || '');
            if (/f_AL=|\\/jobs\\/search|\\/jobs\\/collections/.test(h)) return false;
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }""")
    except Exception:
        return False


def _easy_apply_button(page, wait: float = 10):
    """The job's Easy Apply button, or None if the job only has a normal Apply button (or none).
    Never returns a filter or menu link that merely says 'Easy Apply'."""
    end = time.time() + wait
    while True:
        saw_apply = False
        for role in ("button", "link"):
            cands = page.get_by_role(role, name=APPLY_ANY)
            for k in range(min(cands.count(), 10)):
                c = cands.nth(k)
                if not _is_job_button(c):
                    continue
                saw_apply = True
                try:
                    name = (c.get_attribute("aria-label") or "") + " " + (c.inner_text() or "")
                except Exception:
                    continue
                if EASY_NAME.search(name):
                    return c
        if saw_apply or time.time() > end:
            return None  # the job's apply button is there and it isn't Easy Apply
        time.sleep(1)


def apply(page, job_url: str, cv_pdf: Path, ctx: dict, submit: bool = True) -> Result:
    page.goto(job_url, wait_until="domcontentloaded")
    pause(2, 4)
    if page.get_by_text(re.compile(r"Applied \d+ \w+ ago|Application submitted", re.I)).count():
        return Result("already_applied")
    btn = _easy_apply_button(page)
    if btn is None:
        return Result("not_easy_apply", "No Easy Apply button (the job may apply on the company site or be closed)")
    job_id = re.sub(r"\D", "", job_url.rstrip("/").split("/")[-1])
    btn.click()
    pause(1.5, 3)
    if job_id and job_id not in page.url and "/apply" not in page.url:
        # the click left the job (it wasn't the job's own button); don't go further
        page.goto(job_url, wait_until="domcontentloaded")
        return Result("not_easy_apply", "No Easy Apply button (the job may apply on the company site or be closed)")
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
