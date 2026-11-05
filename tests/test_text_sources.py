from jobapplier.sources import ashby, greenhouse, lever
from jobapplier.text import html_to_text, parse_date, parse_salary


def test_salary_parsing():
    assert parse_salary("Salary: £60,000 - £70,000 + bonus") == (60000, 70000)
    assert parse_salary("£60k-£75k") == (60000, 75000)
    assert parse_salary("up to £85,000") == (85000, 85000)
    assert parse_salary("competitive") == (None, None)


def test_html_and_dates():
    assert "Build pipelines" in html_to_text("&lt;p&gt;Build pipelines&lt;/p&gt;")
    assert parse_date("2026-10-28T13:54:03-04:00").year == 2026
    assert parse_date(1761000000000).year == 2025
    assert parse_date("05/11/2026").month == 11


def test_greenhouse_parse():
    data = {"jobs": [{"title": "Data Engineer", "company_name": "Monzo", "location": {"name": "London"},
                      "absolute_url": "https://job-boards.greenhouse.io/monzo/jobs/1",
                      "first_published": "2026-10-28T13:54:03-04:00", "content": "&lt;p&gt;£70,000 - £80,000&lt;/p&gt;"}]}
    j = greenhouse.parse(data, "Monzo")[0]
    assert (j.company, j.salary_min, j.apply_method) == ("Monzo", 70000, "auto")


def test_lever_and_ashby_parse():
    lj = lever.parse([{"text": "ML Engineer", "categories": {"location": "London"}, "hostedUrl": "https://jobs.lever.co/x/1",
                       "applyUrl": "https://jobs.lever.co/x/1/apply", "createdAt": 1761000000000,
                       "descriptionPlain": "Python", "lists": [{"text": "You have", "content": "<li>SQL</li>"}]}], "X")[0]
    assert "SQL" in lj.description and lj.apply_method == "auto"
    aj = ashby.parse({"jobs": [{"title": "AI Engineer", "location": "London", "jobUrl": "https://jobs.ashbyhq.com/y/1",
                                "publishedAt": "2026-10-30T10:00:00.000+00:00", "descriptionPlain": "LLMs",
                                "isRemote": False, "compensation": {"compensationTierSummary": "£65K – £80K"}}]}, "Y")[0]
    assert aj.salary_max == 80000
