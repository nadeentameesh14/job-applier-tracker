from jobapplier.sources.linkedin import job_id_from, parse_cards, parse_detail

CARDS = """
<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:4012345678">
  <a class="base-card__full-link" href="https://uk.linkedin.com/jobs/view/data-engineer-at-acme-4012345678?trk=x"></a>
  <div class="base-search-card__info">
    <h3 class="base-search-card__title">  Senior Data Engineer </h3>
    <h4 class="base-search-card__subtitle"><a>Acme Ltd</a></h4>
    <div class="base-search-card__metadata">
      <span class="job-search-card__salary-info">£60,000.00 - £70,000.00</span>
      <span class="job-search-card__location">London, England, United Kingdom</span>
      <time class="job-search-card__listdate" datetime="2026-11-03">2 days ago</time>
    </div></div></div></li>
<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4099999999">
  <h3 class="base-search-card__title">AI Engineer</h3>
  <h4 class="base-search-card__subtitle">Beta</h4>
  <span class="job-search-card__location">United Kingdom</span></div></li>
"""

DETAIL_OFFSITE = """
<code id="applyUrl" style="display: none"><!--"https://www.linkedin.com/jobs/view/externalApply/4012345678?url=https%3A%2F%2Fboards%2Egreenhouse%2Eio%2Facme%2Fjobs%2F123&urlHash=abc"--></code>
<div class="show-more-less-html__markup"><p>We need <strong>Python</strong> and SQL.</p></div>
<ul><li class="description__job-criteria-item"><h3>Seniority level</h3><span>Mid-Senior level</span></li></ul>
"""

DETAIL_EASY = """
<button data-tracking-control-name="public_jobs_apply-link-onsite">Easy Apply</button>
<div class="show-more-less-html__markup">Build pipelines.</div>
"""


def test_cards():
    jobs = parse_cards(CARDS, remote=False)
    assert len(jobs) == 2
    j = jobs[0]
    assert (j.title, j.company, j.location) == ("Senior Data Engineer", "Acme Ltd", "London, England, United Kingdom")
    assert j.url == "https://www.linkedin.com/jobs/view/4012345678/" and j.apply_method == "linkedin"
    assert j.salary_min == 60000 and j.salary_max == 70000
    assert j.posted_at.year == 2026
    assert jobs[1].posted_at is None


def test_detail_offsite_and_easy():
    d = parse_detail(DETAIL_OFFSITE)
    assert d["easy_apply"] is False
    assert d["apply_url"] == "https://boards.greenhouse.io/acme/jobs/123"
    assert "Python" in d["description"] and d["seniority"] == "Mid-Senior level"
    e = parse_detail(DETAIL_EASY)
    assert e["easy_apply"] is True and e["apply_url"] == ""


def test_job_id():
    assert job_id_from("https://uk.linkedin.com/jobs/view/data-engineer-at-acme-4012345678?trk=x") == "4012345678"


def test_alert_email_ids():
    from jobapplier.sources.linkedin_alerts import job_ids
    body = ('<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">Data Engineer</a>'
            '<a href="https://www.linkedin.com/comm/jobs/view/4012345678/?refId=y">again</a>'
            'https://www.linkedin.com/jobs/view/senior-ai-engineer-at-beta-4099999999?trk=z')
    assert job_ids(body) == ["4012345678", "4099999999"]


def test_ago():
    from jobapplier.sources.linkedin import ago_to_date
    assert ago_to_date("2 weeks ago") is not None and ago_to_date("Reposted recently") is None
