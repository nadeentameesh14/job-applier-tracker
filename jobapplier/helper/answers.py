"""Answer Easy Apply form questions truthfully from your settings, and from Claude only when needed."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

# (label pattern, settings key or literal) checked in order; first match wins.
RULES: list[tuple[str, str]] = [
    # questions about visa type or expiry: never claim it isn't time-limited (see ASK_YOU / VISA_TEXT below)
    (r"(time-?limited|expir|visa (type|category|status)|type of visa|immigration status|leave to remain)", "__visa__"),
    (r"\b(sponsor|sponsorship)\b", "needs_sponsorship"),
    (r"\b(right to work|authori[sz]ed to work|eligible to work|legally (able|allowed|entitled))\b", "right_to_work"),
    (r"\bnotice\b", "notice_period"),
    (r"\b(salary|compensation|pay expectation|expected (pay|salary)|desired pay)\b", "expected_salary"),
    (r"\b(security clearance|clearance)\b", "security_clearance"),
    (r"\b(position|role|job( title)?) (you are |you're |are you )?applying for\b", "job_title"),
    (r"\bgender\b|\bsex\b", "gender"),
    (r"^(legal |preferred )?first name\b|\bgiven name\b|\bforename\b", "first_name"),
    (r"^(legal )?last name\b|\bsurname\b|\bfamily name\b", "last_name"),
    (r"^(full |your |legal )?name$", "name"),
    (r"\bhow did you (hear|find|learn)\b|\bwhere did you (hear|find|see)\b|\bsource\b", "heard_from"),
    (r"\b(veteran|disabilit\w*)\b", "decline"),
    (r"\b(religio\w*|belief|faith)\b", "religion"),
    # Northern Ireland style "community background" (Protestant / Roman Catholic / Neither)
    (r"\bcommunity background\b", "community_background"),
    (r"\b(ethnic\w*|race|racial)\b", "ethnicity"),
    (r"\b(nationality|citizenship)\b", "nationality"),
    (r"\blinked ?in\b", "linkedin"),
    (r"\b(phone|mobile)\b", "phone"),
    (r"\be-?mail\b", "email"),
    # commuting / on-site questions are always "Yes" (checked before the city rule, which also mentions location)
    (r"\b(commut\w*|relocat\w*|on-?site|hybrid|in the office|office)\b", "commute"),
    (r"\b(address|city|location|where are you based)\b", "city"),
]

# What to write when a free-text box asks for visa type or expiry: true, and doesn't volunteer the date.
VISA_TEXT = "I have the right to work in the UK and I am currently on my graduate visa. Happy to share details and documents at offer stage."


def lookup(label: str, profile: dict, answers: dict) -> str | None:
    low = " ".join(label.lower().replace("*", " ").split())
    known = {**{k: str(v) for k, v in profile.items()}, **{k: str(v) for k, v in answers.items()}}
    known.setdefault("city", known.get("location", "London, United Kingdom"))
    if known.get("linkedin") and not known["linkedin"].startswith("http"):
        known["linkedin"] = "https://www." + known["linkedin"].removeprefix("www.")
    known.setdefault("commute", "Yes")
    known.setdefault("heard_from", "LinkedIn")
    known.setdefault("decline", "Prefer not to say")
    if known.get("name"):
        parts = known["name"].split()
        known.setdefault("first_name", parts[0])
        known.setdefault("last_name", " ".join(parts[1:]) or parts[0])
    if known.get("religion") and known.get("religion", "").lower() not in ("christian", "catholic", "protestant"):
        known.setdefault("community_background", "Neither")
    for pat, key in RULES:
        if re.search(pat, low):
            if key == "__visa__":
                return "__visa__"
            v = known.get(key)
            if v:
                return v
    return None


CLAUDE_PATHS = ["~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
LEARNED = Path.home() / ".job-applier" / "learned_answers.json"
last_problem: str = ""


def clean_answer(raw: str, label: str = "") -> str:
    """Keep only the final answer: the <answer> tag if present, no markdown, and just the number for
    'how many years' questions."""
    m = re.findall(r"<answer>(.*?)</answer>", raw, re.S | re.I)
    ans = (m[-1] if m else raw).strip()
    ans = ans.replace("**", "").strip()
    if re.search(r"how many (years|months)", label, re.I):
        nums = re.findall(r"\d+(?:\.\d+)?", ans)
        if nums:
            return nums[-1]
    if re.search(r"answer:\s*", ans, re.I) and not m:
        ans = re.split(r"answer:\s*", ans, flags=re.I)[-1].strip()
    ans = re.sub(r"\bUNKNOWN\b", "0", ans) if "\n" in ans else ans
    return ans


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


MOTIVATION = re.compile(
    r"\bwhy (do you|are you|would you|this|us|join|should we)|\bwhat (excites|interests|attracts|draws|motivates) you"
    r"|\binterest(ed)? in (this|the|our|joining)|\bcover (letter|note)|\btell us (about|why)|\bmotivat"
    r"|\bwhat (makes you|would you bring)|\bwhy .{0,40}\b(role|company|team|position|join)\b"
    r"|^\s*why\s+[\w&.'-]+(\s+[\w&.'-]+)?\s*\??\s*\*?\s*$", re.I)


def write_motivation(exe: str, label: str, cv_text: str, profile: dict, answers: dict, job: str) -> str | None:
    """'Why do you want to join us?' and the like: research the company, then link what's interesting about it
    to the candidate's real experience. Uses web search through Claude Code."""
    global last_problem
    prompt = (
        "Write the candidate's answer to this job-application question, in the first person, as the candidate.\n"
        "1) Research the company first (web search their site, product, mission and recent news) and pick one or two "
        "specific things that are genuinely interesting or relevant to this role.\n"
        "2) Connect them to the candidate's real skills and experience from the CV, and say how that would help the "
        "company in this role. Use only experience that is on the CV or in the facts: never invent anything.\n"
        "Style: warm, specific and confident, plain English, 80 to 150 words (shorter if the box looks small), "
        "no greeting or sign-off, no bullet points, no em dashes. Don't mention visas, salary or notice period.\n\n"
        f"<question>{label}</question>\n<job>{job}</job>\n<cv>\n{cv_text}\n</cv>\n"
        f"<facts>\n{json.dumps({k: v for k, v in {**profile, **answers}.items() if k not in ('expected_salary', 'phone', 'email')}, default=str)}\n</facts>\n"
        "Reply with ONLY the final answer inside <answer></answer> tags."
    )
    try:
        r = subprocess.run([exe, "-p", "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch",
                            "--model", "sonnet"], input=prompt, capture_output=True, text=True, timeout=300)
    except Exception as e:
        last_problem = f"Claude Code didn't run: {e}"
        return None
    ans = clean_answer(r.stdout or "")
    if r.returncode or not ans or ans.upper().startswith("UNKNOWN"):
        last_problem = "Claude couldn't write the answer: " + ((r.stderr or r.stdout or "").strip()[-200:])
        return None
    return ans.replace("\u2014", ", ").strip()


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
    if not options and MOTIVATION.search(label):
        return write_motivation(exe, label, cv_text, profile, answers, job)
    prompt = (
        "You fill in one job-application question for the candidate below. Answer ONLY from the CV and facts; "
        "never invent experience. If they don't settle it, answer exactly UNKNOWN. For years of experience, count "
        "from the CV dates and give a whole number (just the number if the question asks how many years). If the "
        "CV shows no experience with a tool, say so honestly (e.g. 'No' or '0'). If options are given, answer with "
        "one option's exact text. Keep free-text answers short (one or two sentences).\n"
        "For 'how many years of experience with X' questions never answer UNKNOWN: add up the CV roles where X (or "
        "clearly the same work) appears and give a whole number; if X is only in the skills list, count it from the current role; 0 if it doesn't appear at all.\n\n"
        f"<cv>\n{cv_text}\n</cv>\n<facts>\n{json.dumps({**profile, **answers}, default=str)}\n</facts>\n"
        f"<job>{job}</job>\n<question>{label}</question>\n"
        + (f"<options>{json.dumps(options)}</options>\n" if options else "")
        + "Think silently. Reply with ONLY the final answer inside <answer></answer> tags, with no explanation. "
          "For a question listing several tools, give one line per tool like 'SQL: 2', using 0 for none (never UNKNOWN)."
    )
    try:
        r = subprocess.run([exe, "-p", "--tools", "", "--model", "haiku"], input=prompt,
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        last_problem = f"Claude Code didn't run: {e}"
        return None
    ans = clean_answer(r.stdout or "", label)
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
    general = not re.search(r"\b(why|this (role|job|company|position)|cover letter|tell us|describe)\b", label, re.I)
    if not general or (not options and len(ans) > 40):
        return ans  # specific to this job: don't reuse it elsewhere
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
    if v.startswith("prefer not") or v.startswith("decline"):
        for o in options:
            if re.search(r"decline|(not|n.t) (wish|want|to (say|answer|disclose))|prefer not|rather not", o, re.I):
                return o
        return None
    if v in ("yes", "no"):
        for o in options:
            if re.match(rf"{v}\b", o.strip().lower()):
                return o
        return None
    for o in options:
        ol = o.strip().lower()
        if not v or ol in ("select an option", ""):
            continue
        if re.search(rf"\b{re.escape(v)}\b", ol) or (len(ol) > 3 and re.search(rf"\b{re.escape(ol)}\b", v)):
            return o
    return None
