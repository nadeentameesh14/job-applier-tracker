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

MODAL = "div.jobs-easy-apply-modal, div[data-test-modal], div.artdeco-modal"


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
                const id = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (id) return id.innerText;
                const fs = el.closest('fieldset'); if (fs) { const l = fs.querySelector('legend'); if (l) return l.innerText; }
                const g = el.closest('.jobs-easy-apply-form-element, .fb-dash-form-element, div');
                const l = g && g.querySelector('label, span.t-bold'); return l ? l.innerText : (el.getAttribute('aria-label') || '');
            }"""
        )
    except Exception:
        txt = ""
    return " ".join((txt or "").split())


def _fill_step(modal, ctx: dict) -> list[str]:
    """Fill every empty field in the current step. Returns labels it couldn't answer."""
    unknown: list[str] = []

    def answer(label: str, options: list[str] | None = None) -> str | None:
        v = A.lookup(label, ctx["profile"], ctx["answers"])
        if v and options:
            v = A.pick_option(v, options)
        if v is None:
            v = A.ask_claude(label, options or [], ctx["cv_text"], ctx["profile"], ctx["answers"], ctx["job"])
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
            legend = fs.locator("legend, span.fb-dash-form-element__label").first
            label = " ".join(legend.inner_text().split()) if legend.count() else _label_for(fs)
            opts = [" ".join(t.split()) for t in fs.locator("label").all_inner_texts()]
            v = answer(label, opts)
            if v is None:
                unknown.append(label or "a choice")
                continue
            fs.locator("label", has_text=v).first.click()
            pause(0.3, 0.8)
        except Exception:
            continue
    return unknown


def apply(page, job_url: str, cv_pdf: Path, ctx: dict, submit: bool = True) -> Result:
    page.goto(job_url, wait_until="domcontentloaded")
    pause(2, 4)
    if page.get_by_text(re.compile(r"Applied \d+ \w+ ago|Application submitted", re.I)).count():
        return Result("already_applied")
    btn = page.locator("button.jobs-apply-button, button:has-text('Easy Apply')").first
    if not btn.count() or "easy apply" not in (btn.inner_text() or "").lower():
        return Result("not_easy_apply", "No Easy Apply button (the job may apply on the company site or be closed)")
    btn.click()
    pause(1.5, 3)
    ctx = {**ctx, "cv_pdf": str(cv_pdf)}
    for step in range(12):
        modal = page.locator(MODAL).first
        if not modal.count():
            return Result("error", "The Easy Apply window didn't open")
        follow = modal.locator("input#follow-company-checkbox:checked")
        if follow.count():
            modal.locator("label[for=follow-company-checkbox]").click()
        unknown = _fill_step(modal, ctx)
        submit_btn = modal.locator("button[aria-label='Submit application'], button:has-text('Submit application')").first
        if submit_btn.count() and submit_btn.is_visible():
            if not submit:
                return Result("needs_you", "Test mode: everything is filled in; review it and press Submit yourself")
            submit_btn.click()
            pause(2, 4)
            done = page.locator("button[aria-label='Dismiss'], button:has-text('Done')").first
            if done.count():
                done.click()
            return Result("applied")
        nxt = modal.locator("button[aria-label='Continue to next step'], button[aria-label='Review your application'], "
                            "button:has-text('Next'), button:has-text('Review')").first
        if not nxt.count():
            return Result("needs_you", "Couldn't find the Next button")
        nxt.click()
        pause(1.5, 3)
        errs = modal.locator(".artdeco-inline-feedback--error, [data-test-form-element-error-messages]")
        if any(x.is_visible() and x.inner_text().strip() for x in errs.all()):
            missing = ", ".join(u for u in unknown if u) or "a required question"
            return Result("needs_you", f"Couldn't answer: {missing}")
    return Result("needs_you", "Too many steps; left open for you")
