"""Shared data types."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    source: str  # greenhouse | lever | ashby | adzuna | reed | manual
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted_at: datetime | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    remote: bool = False
    apply_url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        key = f"{self.company.strip().lower()}|{self.title.strip().lower()}|{self.url}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    @property
    def dedupe_key(self) -> str:
        """Same role at the same company from two sources counts once."""
        return f"{self.company.strip().lower()}|{self.title.strip().lower()}"

    @property
    def apply_method(self) -> str:
        """How this job would be applied to: auto (company ATS form), linkedin (needs approval), manual."""
        u = (self.apply_url or self.url).lower()
        if "linkedin.com" in u:
            return "linkedin"
        if any(h in u for h in ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com")):
            return "auto"
        return "manual"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        d["id"] = self.id
        d["apply_method"] = self.apply_method
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        d = {k: v for k, v in d.items() if k not in {"id", "apply_method"}}
        if d.get("posted_at"):
            d["posted_at"] = datetime.fromisoformat(d["posted_at"])
        return cls(**d)
