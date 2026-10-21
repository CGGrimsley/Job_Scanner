from job_scanner import profile, scoring

P = profile.clean({"target_titles": ["Data Analyst"], "skills": ["SQL", "Python", "Tableau"], "locations": ["Raleigh, NC"],
                   "min_salary": 60000, "seniority": ["entry", "mid"], "avoid_keywords": ["commission only"]})


def test_strong_match_reads_apply():
    r = scoring.score({"title": "Data Analyst II", "location": "Raleigh, NC (Hybrid)", "pay_text": "$65,000 - $80,000 a year",
                       "posted_text": "3 days ago", "description": "SQL and Python every day"}, P)
    assert r["verdict"] == "Apply" and r["score"] >= 80
    assert r["remote"] == "hybrid" and r["pay_max"] == 80000


def test_avoid_list_caps_score():
    r = scoring.score({"title": "Data Analyst", "location": "Raleigh, NC", "description": "Commission only role"}, P)
    assert r["verdict"] == "Skip" and r["score"] <= 25
    assert "avoid list" in r["cautions"][0]


def test_wrong_level_and_title_is_skip():
    r = scoring.score({"title": "Senior Software Engineer", "location": "Remote"}, P)
    assert r["verdict"] == "Skip"


def test_pay_parsing():
    assert scoring.pay_of("$22.50 an hour") == (46800, 46800)
    assert scoring.pay_of("$85K - $100K") == (85000, 100000)
    assert scoring.pay_of("From $4,000 a month") == (48000, 48000)
    assert scoring.pay_of("$18 - $20/hr") == (37440, 41600)
    assert scoring.pay_of("$18 - 20 an hour") == (37440, 41600)
    assert scoring.pay_of("$65K/yr - $80K/yr") == (65000, 80000)
    assert scoring.pay_of("no pay here") == (None, None)


def test_posted_days():
    assert scoring.posted_days("Just posted") == 0
    assert scoring.posted_days("Posted 30+ days ago") == 30
    assert scoring.posted_days("2 weeks ago") == 14
    assert scoring.posted_days("Reposted 3 days ago") == 3


def test_levels():
    assert scoring.level_of("Sr. Data Engineer") == "senior"
    assert scoring.level_of("Junior Developer") == "entry"
    assert scoring.level_of("Director of Analytics") == "director"
    assert scoring.level_of("Data Analyst") == "mid"


def test_empty_profile_says_so():
    r = scoring.score({"title": "Anything"}, profile.clean({}))
    assert "Profile" in r["cautions"][0]


def test_card_alone_is_capped():
    card = {"title": "Data Analyst", "location": "Raleigh, NC (Hybrid)", "pay_text": "$65,000 - $80,000 a year", "posted_text": "today"}
    assert scoring.score(card, P)["score"] <= 75
