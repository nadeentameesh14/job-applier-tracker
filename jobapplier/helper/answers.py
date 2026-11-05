"""Answer Easy Apply form questions truthfully from your settings, and from Claude only when needed."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

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
    # commuting / on-site questions are always "Yes" (checked before the city rule, which also mentions location)
    (r"\b(commut\w*|relocat\w*|on-?site|hybrid|in the office|office)\b", "commute"),
    (r"\b(city|location|where are you based)\b", "city"),
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


CLAUDE_PATHS = ["~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
LEARNED = Path.home() / ".job-applier" / "learned_answers.json"
last_problem: str = ""


def find_claude() -> str | None:
    """Where Claude Code is installed (the helper may run without your normal Terminal PATH)."""
    exe = shutil.which("claude")
    if exe:
        return exe
    for c in CLAUDE_PATHS:
        p = Path(c).expanduser()
        if p.exists():
            return str(p)
    return None


def _key(label: str, options: list[str]) -> str:
    return re.sub(r"[^a-z0-9 ]", "", label.lower()).strip() + ("|" + "/".join(sorted(o.lower() for o in options)) if options else "")


def _learned() -> dict:
    try:
        return json.loads(LEARNED.read_text())
    except Exception:
        return {}


def ask_claude(label: str, options: list[str], cv_text: str, profile: dict, answers: dict, job: str) -> str | None:
    """Ask Claude Code (your subscription) for a truthful answer. Returns None when it can't tell from the CV.
    Answers to general questions are remembered in ~/.job-applier/learned_answers.json (you can edit it)."""
    global last_problem
    if not label:
        return None
    known = _learned()
    k = _key(label, options)
    if k in known and known[k]:
        return known[k]
    exe = find_claude()
    if not exe:
        last_problem = "Claude Code isn't installed on this computer, so questions not in your settings can't be answered"
        return None
    prompt = (
        "You fill in one job-application question for the candidate below. Answer ONLY from the CV and facts; "
        "never invent experience. If they don't settle it, answer exactly UNKNOWN. For years of experience, count "
        "from the CV dates and give a whole number (just the number if the question asks how many years). If the "
        "CV shows no experience with a tool, say so honestly (e.g. 'No' or '0'). If options are given, answer with "
        "one option's exact text. Keep free-text answers short (one or two sentences).\n\n"
        f"<cv>\n{cv_text}\n</cv>\n<facts>\n{json.dumps({**profile, **answers}, default=str)}\n</facts>\n"
        f"<job>{job}</job>\n<question>{label}</question>\n"
        + (f"<options>{json.dumps(options)}</options>\n" if options else "")
        + "Reply with the answer only."
    )
    try:
        r = subprocess.run([exe, "-p", "--tools", "", "--model", "haiku"], input=prompt,
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        last_problem = f"Claude Code didn't run: {e}"
        return None
    ans = (r.stdout or "").strip()
    if r.returncode or not ans:
        last_problem = "Claude Code isn't signed in or hit a limit: " + ((r.stderr or r.stdout or "").strip()[-200:])
        return None
    if ans.upper().startswith("UNKNOWN"):
        return None
    if options:
        match = [o for o in options if o.strip().lower() == ans.lower()] or \
                [o for o in options if o.strip().lower() == ans.splitlines()[-1].strip().lower()]
        if not match:
            return None
        ans = match[0]
    try:
        known[k] = ans
        LEARNED.parent.mkdir(parents=True, exist_ok=True)
        LEARNED.write_text(json.dumps(known, indent=2))
    except Exception:
        pass
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
