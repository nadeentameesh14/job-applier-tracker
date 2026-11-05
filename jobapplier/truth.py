"""Truthfulness guard: a tailored CV may only mention skills, tools and numbers that the master CV
(or the user's declared extra_skills) already contains."""
from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources


@lru_cache
def vocab() -> tuple[str, ...]:
    text = resources.files("jobapplier").joinpath("skills_vocab.txt").read_text()
    return tuple(l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#"))


def _pattern(term: str, case_sensitive: bool) -> re.Pattern:
    # word boundaries that also work for terms like "C++", "CI/CD", "Node.js"
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", 0 if case_sensitive else re.I)


def _mentions(term: str, text: str) -> bool:
    """Is the skill named in new text? Single words must match case ("Spark", not "spark interest")."""
    return bool(_pattern(term, " " not in term).search(text))


def _known(term: str, text: str) -> bool:
    """Is the skill anywhere in the master CV? Case-insensitive, so "pandas" covers "Pandas"."""
    return bool(_pattern(term, False).search(text))


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def violations(new_text: str, master_text: str, extra_skills: list[str] | None = None) -> list[str]:
    """Return a list of reasons new_text is not supported by master_text (+ extra_skills)."""
    allowed = master_text + "\n" + "\n".join(extra_skills or [])
    out = []
    for term in vocab():
        if _mentions(term, new_text) and not _known(term, allowed):
            out.append(f"mentions '{term}' which is not on your CV")
    master_nums = set(_NUM.findall(allowed))
    for n in _NUM.findall(new_text):
        if n not in master_nums:
            out.append(f"number '{n}' is not on your CV")
    return out
