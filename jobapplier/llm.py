"""Claude calls: screen jobs, analyse a job description against the CV, and propose truthful edits.

Two ways to reach Claude:
  provider "claude-code" (default): the Claude Code CLI, signed in with your Claude subscription
      (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`). No per-use API bill.
  provider "anthropic": the Claude API with ANTHROPIC_API_KEY, billed per use.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

M = TypeVar("M", bound=BaseModel)


class AuthError(RuntimeError):
    """Sign-in or usage problem: every later call would fail too, so the run should stop."""


class LLM:
    def __init__(self, provider: str = "claude-code"):
        if provider not in {"claude-code", "anthropic"}:
            raise ValueError(f"unknown provider '{provider}' (use claude-code or anthropic)")
        self.provider = provider
        self._client = None

    def parse(self, model: str, system: str, prompt: str, schema: type[M], max_tokens: int = 16000) -> M:
        if self.provider == "claude-code":
            return self._claude_code(model, system, prompt, schema)
        return self._api(model, system, prompt, schema, max_tokens)

    def _claude_code(self, model: str, system: str, prompt: str, schema: type[M]) -> M:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("Claude Code is not installed (npm install -g @anthropic-ai/claude-code)")
        cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--model", model,
               "--system-prompt", system, "--json-schema", json.dumps(schema.model_json_schema())]
        env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            # tokens copied from a terminal often pick up line breaks where the text wrapped
            env["CLAUDE_CODE_OAUTH_TOKEN"] = "".join(env["CLAUDE_CODE_OAUTH_TOKEN"].split())
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, env=env)
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"Claude Code failed: {(r.stderr or r.stdout)[-500:]}")
        if out.get("is_error"):
            msg = str(out.get("result"))[:500]
            if any(w in msg.lower() for w in ("auth", "login", "log in", "credit balance", "usage limit", "limit reached",
                                              "hit your limit", "rate limit", "invalid token", "oauth", "expired", "unauthor", "401", "quota")):
                raise AuthError(f"Claude Code can't sign in or is out of usage: {msg}")
            raise RuntimeError(f"Claude Code error: {msg}")
        data = out.get("structured_output")
        if data is None:
            data = json.loads(out.get("result") or "null")
        return schema.model_validate(data)

    def _api(self, model: str, system: str, prompt: str, schema: type[M], max_tokens: int) -> M:
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic()
        kw = {}
        if not model.startswith("claude-haiku"):
            # Re-run on a fallback model if a safety classifier declines (rare for CVs).
            kw = {"extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"},
                  "extra_body": {"fallbacks": "default"}}
        resp = self._client.messages.parse(model=model, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": prompt}],
                                           output_format=schema, **kw)
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude declined to process this job advert")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise RuntimeError(f"Claude's answer was incomplete (stop_reason={resp.stop_reason})")
        return resp.parsed_output


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
    red_flags: list[str] = Field(description="Only hard deal-breakers that rule the candidate out whatever their skills: e.g. security "
                                             "clearance or citizenship they can't meet, a location outside their area, a contract/day-rate "
                                             "role when they want permanent, or sponsorship-only. Use the candidate facts: don't list "
                                             "anything they already meet. Skill gaps and experience level belong in concerns, not here")
    concerns: list[str] = Field(default_factory=list, description="Gaps a recruiter may notice (missing skills, fewer years)")
    summary: str = Field(description="Rewritten summary paragraph (S1), about the same length as the original")
    bullet_edits: list[Edit] = Field(description="Rewritten experience bullets (B ids) - only those worth changing")
    bullet_order: list[str] = Field(description="Experience bullet ids, most relevant first")
    skills_edits: list[Edit] = Field(description="Rewritten skills lines (K ids), keeping each line's label")
    drop_order: list[str] = Field(description="B and X ids that matter least for this job, least relevant first, "
                                              "used only if the CV runs over one page. Put quantified achievements "
                                              "(numbers, results) and publications last")


class Screen(BaseModel):
    fit_score: int = Field(description="0-100: how well the candidate's real experience matches the role")
    reason: str = Field(description="One sentence")
    red_flags: list[str] = Field(description="Only hard deal-breakers that rule the candidate out whatever their skills: e.g. security "
                                             "clearance or citizenship they can't meet, a location outside their area, a contract/day-rate "
                                             "role when they want permanent, or sponsorship-only. Use the candidate facts: don't list "
                                             "anything they already meet. Skill gaps and experience level belong in concerns, not here")
    concerns: list[str] = Field(default_factory=list, description="Gaps a recruiter may notice (missing skills, fewer years)")


SCREEN_SYSTEM = """You screen job adverts for one candidate. Score how well the candidate's real CV fits the role \
(0-100), judging skills, experience level and domain. Be strict: 70+ means a recruiter would likely shortlist them. \
Count all of the candidate's relevant professional experience, including adjacent technical roles, not only the \
current job title. Candidate facts (right to work, location, notice period) are true even if the CV doesn't say them. \
If the facts include the candidate's own rules for judging fit, follow them."""


def screen(llm: LLM, model: str, job_text: str, cv_text: str, facts: str = "") -> Screen:
    """Cheap first pass so only promising jobs reach the (more expensive) tailoring step."""
    return llm.parse(model, SCREEN_SYSTEM,
                     f"<job_advert>\n{job_text}\n</job_advert>\n\n<cv>\n{cv_text}\n</cv>\n\n"
                     f"<candidate_facts>\n{facts or 'none given'}\n</candidate_facts>", Screen, max_tokens=4000)


SYSTEM = """You tailor a candidate's CV to one job advert so it passes applicant tracking systems (ATS) \
while staying 100% truthful. You are editing the candidate's real CV; a recruiter will check it at interview.

Hard rules:
- Never add a skill, tool, employer, title, date, metric or number that is not in the CV text or the declared \
extra skills. If the advert wants something the candidate lacks, mark it "missing" and leave it out of the CV.
- You may: reuse the advert's exact wording for experience the CV already shows ("ETL pipelines" -> "ETL/ELT \
pipelines" only if ELT is in the CV or extra skills), spell out an acronym once ("Amazon Web Services (AWS)"), \
reorder bullets and skills so must-haves come first, and shift the summary's emphasis to the role.
- Keep British spelling and the candidate's voice. The CV must stay on one page, so the summary and every \
edited bullet or skills line must be no longer than the original (same length or shorter).
- Keep each skills line's label (the text before the colon) unchanged.
- Don't stuff keywords: each bullet must still read as a natural sentence about real work.
- Only include bullets in bullet_edits that you actually changed.
- The candidate facts (right to work, notice period, location) are for judging fit only. Never write them into the CV."""


def tailor(llm: LLM, model: str, job_text: str, cv_outline: str, extra_skills: list[str], facts: str = "") -> Tailoring:
    prompt = (
        f"<candidate_facts>\n{facts or 'none given'}\n</candidate_facts>\n\n"
        f"<job_advert>\n{job_text}\n</job_advert>\n\n"
        f"<cv>\n{cv_outline}\n</cv>\n\n"
        f"<extra_skills>{', '.join(extra_skills) or 'none'}</extra_skills>\n\n"
        "Analyse the advert's keywords against the CV, score the fit, then return the tailoring edits."
    )
    return llm.parse(model, SYSTEM, prompt, Tailoring)
