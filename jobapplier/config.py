"""Load and validate settings.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Company:
    name: str
    ats: str
    token: str


@dataclass
class Search:
    roles: list[str]
    exclude_title_words: list[str] = field(default_factory=list)
    max_age_days: int = 21
    locations: list[str] = field(default_factory=list)
    remote_ok: bool = True
    country: str = "UK"
    min_salary: int = 0
    currency: str = "GBP"
    exclude_companies: list[str] = field(default_factory=list)
    companies: list[Company] = field(default_factory=list)
    adzuna: dict[str, Any] = field(default_factory=dict)
    reed: dict[str, Any] = field(default_factory=dict)
    linkedin: dict[str, Any] = field(default_factory=dict)


@dataclass
class Settings:
    profile: dict[str, str]
    cv_path: Path
    max_pages: int
    search: Search
    min_fit_score: int
    provider: str
    model: str
    screen_model: str
    extra_skills: list[str]
    answers: dict[str, Any]
    apply: dict[str, int]
    root: Path
    max_screen: int = 60

    def candidate_facts(self) -> str:
        """Facts the AI should take as true even though a CV doesn't state them."""
        a, s = self.answers, self.search
        lines = []
        if a.get("right_to_work"):
            lines.append(f"Right to work in {s.country}: {a['right_to_work']}")
        if a.get("needs_sponsorship"):
            lines.append(f"Needs visa sponsorship: {a['needs_sponsorship']}")
        if s.locations:
            lines.append(f"Based in / will work in: {', '.join(s.locations[:3])}" + (", or remote" if s.remote_ok else ""))
        if a.get("notice_period"):
            lines.append(f"Notice period: {a['notice_period']}")
        if a.get("experience"):
            lines.append(f"Experience and level wanted: {a['experience']}")
        if self.extra_skills:
            lines.append(f"Also has these skills (not written on the CV): {', '.join(self.extra_skills)}")
        if a.get("security_clearance"):
            lines.append(f"Security clearance: {a['security_clearance']}")
        return "\n".join(lines)


def load_settings(path: str | Path = "settings.yaml") -> Settings:
    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"{path} not found. Copy settings.example.yaml to settings.yaml and edit it (see docs/SETUP.md)."
        )
    raw = yaml.safe_load(path.read_text()) or {}
    s = raw.get("search") or {}
    if not s.get("roles"):
        raise SystemExit("settings: search.roles must list at least one job title")
    companies = [Company(**c) for c in (s.get("companies") or [])]
    for c in companies:
        if c.ats not in {"greenhouse", "lever", "ashby"}:
            raise SystemExit(f"settings: company {c.name} has unknown ats '{c.ats}' (use greenhouse, lever or ashby)")
    search = Search(
        roles=list(s["roles"]),
        exclude_title_words=list(s.get("exclude_title_words") or []),
        max_age_days=int(s.get("max_age_days", 21)),
        locations=list(s.get("locations") or []),
        remote_ok=bool(s.get("remote_ok", True)),
        country=str(s.get("country", "UK")),
        min_salary=int(s.get("min_salary") or 0),
        currency=str(s.get("currency", "GBP")),
        exclude_companies=list(s.get("exclude_companies") or []),
        companies=companies,
        adzuna=dict(s.get("adzuna") or {}),
        reed=dict(s.get("reed") or {}),
        linkedin=dict(s.get("linkedin") or {}),
    )
    m = raw.get("matching") or {}
    root = path.resolve().parent
    return Settings(
        profile=dict(raw.get("profile") or {}),
        cv_path=root / raw.get("cv_path", "cv/cv.docx"),
        max_pages=int(raw.get("max_pages", 1)),
        search=search,
        min_fit_score=int(m.get("min_fit_score", 70)),
        provider=str(m.get("provider", "claude-code")),
        model=str(m.get("model", "sonnet")),
        screen_model=str(m.get("screen_model", "haiku")),
        extra_skills=list(raw.get("extra_skills") or []),
        answers=dict(raw.get("answers") or {}),
        apply={k: int(v) for k, v in (raw.get("apply") or {}).items()},
        root=root,
        max_screen=int(m.get("max_screen_per_run", 60)),
    )
