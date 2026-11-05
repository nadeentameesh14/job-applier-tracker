from jobapplier.helper.answers import clean_answer, lookup, pick_option
from jobapplier.helper.careersite import application_url, supported

P = {"name": "Ada Lovelace", "email": "ada@example.com", "linkedin": "linkedin.com/in/ada"}
A = {"right_to_work": "Yes", "needs_sponsorship": "No", "gender": "Female", "religion": "Muslim", "job_title": "Data Engineer"}


def test_lookup_rules():
    assert lookup("First Name*", P, A) == "Ada"
    assert lookup("Last name", P, A) == "Lovelace"
    assert lookup("LinkedIn Profile", P, A) == "https://www.linkedin.com/in/ada"
    assert lookup("Are you comfortable commuting to this job's location?", P, A) == "Yes"
    assert lookup("Position Applying For", P, A) == "Data Engineer"
    assert lookup("Please confirm which community background you identify with:", P, A) == "Neither"
    assert lookup("If your right to work is time-limited, please confirm your visa category and expiry date.", P, A) == "__visa__"
    assert lookup("Do you require sponsorship?", P, A) == "No"


def test_pick_option():
    assert pick_option("Prefer not to say", ["Yes", "No", "I don't wish to answer"]) == "I don't wish to answer"
    assert pick_option("Prefer not to say", ["Yes", "No"]) is None
    assert pick_option("Yes", ["Yes, I am", "No"]) == "Yes, I am"
    assert pick_option("No", ["Yes", "Not sure", "No, I do not"]) == "No, I do not"


def test_clean_answer():
    assert clean_answer("Thinking... Answer: **2**", "How many years of experience with X?") == "2"
    assert clean_answer("<answer>SQL: 2\nRuby: UNKNOWN</answer>") == "SQL: 2\nRuby: 0"


def test_career_urls():
    assert application_url("https://jobs.lever.co/acme/123") == "https://jobs.lever.co/acme/123/apply"
    assert application_url("https://jobs.ashbyhq.com/acme/abc") == "https://jobs.ashbyhq.com/acme/abc/application"
    assert supported("https://job-boards.greenhouse.io/acme/jobs/1") and not supported("https://acme.wd3.myworkdayjobs.com/x")
