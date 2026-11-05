from jobapplier.truth import violations

MASTER = "Built ETL pipelines in Python and SQL on Snowflake with AWS Lambda. 4+ years. 99% CSAT."


def test_allows_rewording_of_real_skills():
    assert violations("Built ETL pipelines on Snowflake using Python, SQL and AWS Lambda", MASTER) == []


def test_blocks_invented_tools_and_numbers():
    v = violations("Built dbt models orchestrated with Airflow, cutting costs 40%", MASTER)
    assert any("dbt" in x for x in v) and any("Airflow" in x for x in v) and any("40" in x for x in v)


def test_extra_skills_are_allowed_and_case_is_sane():
    assert violations("Tracked work in Jira", MASTER, ["Jira"]) == []
    assert violations("Took a rest day", MASTER) == []  # "rest" is not the REST skill
