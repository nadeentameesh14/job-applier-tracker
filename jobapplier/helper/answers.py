"""Answer Easy Apply form questions truthfully from your settings, and from Claude only when needed."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

# (label pattern, settings key or literal) checked in order; first match wins.
RULES: list[tuple[str, str]] = [
    (r"\b(sponsor|sponsorship|visa)\b", "needs_sponsorship"),
    (r"\b(right to work|authori[sz]ed to work|eligible to work|legally (able|allowed|entitled))\b", "right_to_work"),
    (r"\bnotice\b", "notice_period"),
    (r"\b(salary|compensation|pay expectation|expected (pay|salary)|desired pay)\b", "expected_salary"),
    (r"\b(security clearance|clearance)\b", "security_clearance"),
    (r"\b(phone|mobile)\b", "phone"),
    (r"\bemail\b", "email"),
    (r"\blinked ?in\b", "linkedin"),
    (r"\b(city|location|where are you based)\b", "city"),
    (r"\b(commut|relocat|on-?site|hybrid|office)\b", "commute"),
]


def lookup(label: str, profile: dict, answers: dict) -> str | None:
    low = label.lower()
    known = {**{k: str(v) for k, v in profile.items()}, **{k: str(v) for k, v in answers.items()}}
    known.setdefault("city", known.get("location", "London"))
    known.setdefault("commute", "Yes")
    for pat, key in RULES:
        if re.search(pat, low):
            v = known.get(key)
            if v:
                return v
    return None


def ask_claude(label: str, options: list[str], cv_text: str, profile: dict, answers: dict, job: str) -> str | None:
    """Ask Claude Code (your subscription) for a truthful answer. Returns None when it can't tell from the CV."""
    exe = shutil.which("claude")
    if not exe:
        return None
    prompt = (
        "You fill in one job-application question for the candidate below. Answer ONLY from the CV and facts. "
        "If they don't settle it, answer exactly UNKNOWN. For years of experience, count from the CV dates and "
        "give a whole number. If options are given, answer with one option's exact text.\n\n"
        f"<cv>\n{cv_text}\n</cv>\n<facts>\n{json.dumps({**profile, **answers}, default=str)}\n</facts>\n"
        f"<job>{job}</job>\n<question>{label}</question>\n"
        + (f"<options>{json.dumps(options)}</options>\n" if options else "")
        + "Reply with the answer only."
    )
    try:
        r = subprocess.run([exe, "-p", "--tools", "", "--model", "haiku"], input=prompt,
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    out = (r.stdout or "").strip().splitlines()
    ans = out[-1].strip() if out else ""
    if not ans or ans.upper().startswith("UNKNOWN"):
        return None
    if options:
        match = [o for o in options if o.strip().lower() == ans.lower()]
        return match[0] if match else None
    return ans


def pick_option(value: str, options: list[str]) -> str | None:
    """Choose the option that matches a free-text answer ('Yes' -> 'Yes', '3 months' -> '3 months', etc.)."""
    v = value.strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    for o in options:
        if v and (v in o.lower() or o.lower() in v) and o.strip().lower() not in ("select an option", ""):
            return o
    if v in ("yes", "no"):
        for o in options:
            if o.strip().lower().startswith(v):
                return o
    return None
