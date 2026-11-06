"""Apply on company career sites (Greenhouse, Lever, Ashby, Workable) in your own browser.

These forms carry no LinkedIn account risk, so they're submitted without asking you first. It runs on
your laptop rather than in the cloud because these sites often show "are you a robot?" checks to cloud
servers. Jobs found on LinkedIn that apply on a company site are opened while you're signed in, so the
real apply link can be found; if it leads to one of these sites, the helper applies there too.
"""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, unquote, urlparse

from .easyapply import Result, _fill_step, dump_debug, pause

SUPPORTED = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com")
SUCCESS = re.compile(r"thank you for (applying|your application)|application (has been |was )?(submitted|received|sent)"
                     r"|we('ve| have) received your application|successfully (submitted|applied)|thanks for applying", re.I)


def supported(url: str) -> bool:
    return any(h in (url or "").lower() for h in SUPPORTED)


def application_url(url: str) -> str:
    """The page that holds the form for each site."""
    u = url.split("#")[0].rstrip("/")
    if "jobs.lever.co" in u and not u.endswith("/apply"):
        return u + "/apply"
    if "ashbyhq.com" in u and not u.endswith("/application"):
        return u + "/application"
    if "apply.workable.com" in u and "/apply" not in u:
        return u + "/apply/"
    return u


APPLY_NAME = re.compile(r"^\s*apply(\s+now)?\s*$|apply on (the )?company|apply to .{1,80} on (the )?company|^\s*apply\s*(\(|external|opens)", re.I)


def _apply_button(page):
    """LinkedIn's own Apply button for a job that applies on the company site (not Easy Apply, and not
    any other link on the page that happens to contain the word 'apply')."""
    for role in ("button", "link"):
        cands = page.get_by_role(role, name=APPLY_NAME)
        for k in range(min(cands.count(), 8)):
            c = cands.nth(k)
            try:
                if c.is_visible() and "easy apply" not in (c.inner_text() or "").lower():
                    return c
            except Exception:
                continue
    c = page.locator("#jobs-apply-button-id, button.jobs-apply-button, a.jobs-apply-button").first
    return c if c.count() else None


def resolve_linkedin(page, url: str) -> str | None:
    """Open a LinkedIn job while signed in and find where its Apply button leads."""
    page.goto(url, wait_until="domcontentloaded")
    pause(3, 5)
    btn = _apply_button(page)
    if btn is None:
        dump_debug(page, "resolve_" + re.sub(r"\D", "", url)[-12:])
        return None
    href = btn.get_attribute("href") or ""
    if href.startswith("http") and "linkedin.com" not in href:
        return href
    if "url=" in href:
        q = parse_qs(urlparse(href).query).get("url")
        if q:
            return unquote(q[0])
    before = page.url
    try:
        with page.context.expect_page(timeout=20_000) as newp:
            btn.click()
            pause(1.5, 2.5)
            # LinkedIn sometimes asks first ("Share your profile?" / "Continue to apply")
            cont = page.get_by_role("button", name=re.compile(r"^continue|apply on company|^apply$", re.I))
            for k in range(min(cont.count(), 4)):
                c = cont.nth(k)
                if c.is_visible():
                    c.click()
                    break
        tab = newp.value
        try:
            tab.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        pause(2, 3)
        dest = tab.url
        tab.close()
        return dest
    except Exception:
        # some links open in the same tab instead
        if page.url != before and "linkedin.com" not in page.url:
            dest = page.url
            page.go_back()
            return dest
        dump_debug(page, "resolve_" + re.sub(r"\D", "", url)[-12:])
        return None


def _form(page):
    """The application form: the one with the CV upload if there is one."""
    forms = page.locator("form")
    for i in range(forms.count()):
        f = forms.nth(i)
        try:
            if f.locator("input[type=file]").count() and f.is_visible():
                return f
        except Exception:
            continue
    for i in range(forms.count()):
        f = forms.nth(i)
        try:
            if f.locator("input, textarea").count() > 2 and f.is_visible():
                return f
        except Exception:
            continue
    return page.locator("body")


def _empty_required(form) -> list[str]:
    try:
        return form.evaluate("""f => {
            const out = [];
            const els = f.querySelectorAll('input[required], textarea[required], select[required], [aria-required=true]');
            for (const e of els) {
                if (e.type === 'hidden' || e.disabled) continue;
                const r = e.getBoundingClientRect(); if (!r.width && !r.height && e.type !== 'file') continue;
                let empty;
                if (e.type === 'radio') empty = !f.querySelector(`input[type=radio][name="${CSS.escape(e.name)}"]:checked`);
                else if (e.type === 'checkbox') empty = !e.checked;
                else if (e.type === 'file') empty = !(e.files && e.files.length);
                else empty = !(e.value || '').trim();
                if (!empty) continue;
                const lab = (e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label') || e.name || 'a required field';
                out.push(lab.replace(/\\s+/g, ' ').trim());
            }
            return [...new Set(out)];
        }""")
    except Exception:
        return []


def apply(page, url: str, cv_pdf, ctx: dict, submit: bool = True) -> Result:
    page.goto(application_url(url), wait_until="domcontentloaded")
    pause(3, 5)
    if re.search(r"(no longer|not) (accepting|available)|job (has been )?(closed|filled)|page not found|404", page.title() + " "
                 + (page.locator("body").inner_text()[:2000] if page.locator("body").count() else ""), re.I) \
            and not page.locator("input[type=file]").count():
        return Result("closed", "The job is closed or the page is gone")
    # some pages show the advert first, with an Apply button that reveals the form
    if not page.locator("form input, form textarea").count():
        btn = page.get_by_role("button", name=re.compile(r"^apply", re.I)).or_(page.get_by_role("link", name=re.compile(r"^apply", re.I))).first
        if btn.count():
            btn.click()
            pause(2, 4)
    form = _form(page)
    ctx = {**ctx, "cv_pdf": str(cv_pdf)}
    unknown = _fill_step(form, ctx)
    missing = [m for m in _empty_required(form) if m]
    if missing:  # a second pass catches questions that appear after earlier answers
        unknown = _fill_step(form, ctx)
        missing = [m for m in _empty_required(form) if m]
    if missing:
        f = dump_debug(page, re.sub(r"\W+", "_", url)[-50:])
        why = "; ".join(dict.fromkeys(missing + [u for u in unknown if u]))[:400]
        return Result("needs_you", f"Couldn't answer: {why} (page saved to {f})")
    if not submit:
        return Result("needs_you", "Test mode: everything is filled in; review it and press Submit yourself")
    btn = form.get_by_role("button", name=re.compile(r"submit|send application", re.I)).last
    if not btn.count():
        btn = page.get_by_role("button", name=re.compile(r"submit|send application", re.I)).last
    if not btn.count():
        btn = form.get_by_role("button", name=re.compile(r"^apply( now)?$", re.I)).last
    if not btn.count():
        return Result("needs_you", "Couldn't find the Submit button")
    before = page.url
    btn.click()
    end = time.time() + 25
    while time.time() < end:
        time.sleep(2)
        try:
            body = page.locator("body").inner_text()[:5000]
        except Exception:
            body = ""
        if SUCCESS.search(body) or (page.url != before and re.search(r"confirm|thank|success", page.url, re.I)):
            return Result("applied")
    if page.locator("iframe[src*='recaptcha'][title*='challenge'], iframe[src*='hcaptcha']").count():
        return Result("needs_you", "The site wants an 'I'm not a robot' check; finish it and press Submit")
    f = dump_debug(page, re.sub(r"\W+", "_", url)[-50:] + "_submit")
    left = _empty_required(form)
    return Result("needs_you", "Submitted but no confirmation seen" + (f"; still empty: {'; '.join(left)}" if left else "")
                  + f" (page saved to {f})")
