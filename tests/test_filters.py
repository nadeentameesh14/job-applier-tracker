from datetime import datetime, timedelta, timezone

from jobapplier.config import Search
from jobapplier.filters import apply_filters, reject_reason, title_matches
from jobapplier.models import Job

NOW = datetime.now(timezone.utc)
S = Search(roles=["Data Engineer", "ML Engineer", "AI Engineer"], exclude_title_words=["Junior", "Head of"],
           max_age_days=21, locations=["London", "Reading"], remote_ok=True, min_salary=50000,
           exclude_companies=["Mistral Data"])


def job(**kw):
    base = dict(source="greenhouse", title="Senior Data Engineer", company="Acme", location="London",
                url="https://boards.greenhouse.io/acme/jobs/1", posted_at=NOW - timedelta(days=2))
    base.update(kw)
    return Job(**base)


def test_title_matching_and_aliases():
    assert title_matches("Senior Data Engineer", S.roles) == 0
    assert title_matches("Machine Learning Engineer II", S.roles) == 1
    assert title_matches("Product Manager", S.roles) is None


def test_rejections():
    assert reject_reason(job(), S) is None
    assert reject_reason(job(company="Mistral Data"), S) == "excluded company"
    assert "Junior" in reject_reason(job(title="Junior Data Engineer"), S)
    assert reject_reason(job(location="Berlin, Germany"), S).startswith("location")
    assert reject_reason(job(location="Remote (UK)", remote=True), S) is None
    assert reject_reason(job(location="Remote - US", remote=True), S).startswith("location")
    assert reject_reason(job(posted_at=NOW - timedelta(days=40)), S).startswith("posted")
    assert reject_reason(job(salary_max=45000), S).startswith("salary")
    assert reject_reason(job(salary_max=None), S) is None


def test_sorting_dedupe_and_seen():
    a = job(title="AI Engineer", location="Reading")
    b = job(title="Data Engineer", location="London", posted_at=NOW - timedelta(days=5))
    c = job(title="Data Engineer", location="London", source="adzuna", url="https://adzuna/x")
    kept, rejected = apply_filters([a, b, c], S)
    assert [j.title for j in kept] == ["Data Engineer", "AI Engineer"]  # London first
    assert kept[0].source == "greenhouse"  # direct board preferred over aggregator
    kept, rejected = apply_filters([a], S, already_seen={a.dedupe_key})
    assert not kept and rejected[0][1] == "already in tracker"
