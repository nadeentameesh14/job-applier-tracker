"""Claude calls: analyse a job description against the CV and propose truthful tailoring edits."""
from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel, Field


class Keyword(BaseModel):
    term: str = Field(description="Skill, tool or phrase exactly as the job ad writes it")
    must_have: bool
    status: Literal["exact", "reworded", "missing"] = Field(
        description="exact: CV already uses these words; reworded: CV shows this experience in other words; "
        "missing: the candidate's CV has no evidence for it"
    )
    cv_evidence: str = Field(description="Block id(s) proving it, e.g. 'B6, K1', or '' when missing")


class Edit(BaseModel):
    id: str
    text: str


class Tailoring(BaseModel):
    role_family: Literal["data_engineering", "ai_ml_engineering", "data_science", "analytics", "solutions_consulting", "other"]
    seniority: Literal["junior", "mid", "senior", "lead", "unclear"]
    keywords: list[Keyword]
    fit_score: int = Field(description="0-100: how well the candidate's real experience matches the role")
    fit_summary: str = Field(description="One or two sentences on why")
    red_flags: list[str] = Field(description="Deal-breakers such as security clearance, sponsorship-only, non-UK location, "
                                             "or a must-have the candidate clearly lacks")
    summary: str = Field(description="Rewritten summary paragraph (S1), about the same length as the original")
    bullet_edits: list[Edit] = Field(description="Rewritten experience bullets (B ids) - only those worth changing")
    bullet_order: list[str] = Field(description="Experience bullet ids, most relevant first")
    skills_edits: list[Edit] = Field(description="Rewritten skills lines (K ids), keeping each line's label")
    drop_order: list[str] = Field(description="B and X ids that matter least for this job, least relevant first, "
                                              "used only if the CV runs over one page")


SYSTEM = """You tailor a candidate's CV to one job advert so it passes applicant tracking systems (ATS) \
while staying 100% truthful. You are editing the candidate's real CV; a recruiter will check it at interview.

Hard rules:
- Never add a skill, tool, employer, title, date, metric or number that is not in the CV text or the declared \
extra skills. If the advert wants something the candidate lacks, mark it "missing" and leave it out of the CV.
- You may: reuse the advert's exact wording for experience the CV already shows ("ETL pipelines" -> "ETL/ELT \
pipelines" only if ELT is in the CV or extra skills), spell out an acronym once ("Amazon Web Services (AWS)"), \
reorder bullets and skills so must-haves come first, and shift the summary's emphasis to the role.
- Keep British spelling, the candidate's voice, and roughly the same length per bullet (one page matters).
- Keep each skills line's label (the text before the colon) unchanged.
- Don't stuff keywords: each bullet must still read as a natural sentence about real work.
- Only include bullets in bullet_edits that you actually changed."""


def tailor(client: anthropic.Anthropic, model: str, job_text: str, cv_outline: str, extra_skills: list[str]) -> Tailoring:
    prompt = (
        f"<job_advert>\n{job_text}\n</job_advert>\n\n"
        f"<cv>\n{cv_outline}\n</cv>\n\n"
        f"<extra_skills>{', '.join(extra_skills) or 'none'}</extra_skills>\n\n"
        "Analyse the advert's keywords against the CV, score the fit, then return the tailoring edits."
    )
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Tailoring,
        # Re-run on a fallback model if a safety classifier declines (rare for CVs).
        extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this job advert")
    if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
        raise RuntimeError(f"Claude's answer was incomplete (stop_reason={resp.stop_reason})")
    return resp.parsed_output
