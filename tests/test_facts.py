from job_scanner import facts, jobs, profile, scoring, store


def test_years_asked_for():
    assert facts.years("Requirements:\n- 3-5 years of experience in SQL\n- 2+ years with Python")["required"] == 3
    assert facts.years("Minimum of five (5) years' experience as an analyst.")["required"] == 5
    assert facts.years("7+ years of experience preferred. 2 years of experience required.") == {"required": 2, "preferred": 7}
    assert facts.years("We have been in business for 25 years.") is None
    assert facts.years("Applicants must be 18 years old. No experience needed.") is None


def test_degree():
    assert facts.degree("Bachelor's or Master's degree in Computer Science required.") == \
        {"level": "bachelor", "required": True, "equivalent_ok": False}
    assert facts.degree("Bachelor's degree or equivalent work experience.")["equivalent_ok"]
    assert facts.degree("High school diploma or GED.\nBachelor's degree preferred.") == \
        {"level": "high_school", "required": True, "equivalent_ok": False}
    assert facts.degree("A master's degree is a plus.") == {"level": "master", "required": False, "equivalent_ok": False}
    assert facts.degree("Strong Excel skills.") is None


def test_clearance():
    assert facts.clearance("Must hold an active TS/SCI clearance.") == {"level": "ts_sci", "must_hold": True}
    assert facts.clearance("Ability to obtain a Secret clearance.") == {"level": "secret", "must_hold": False}
    assert facts.clearance("Our secret sauce is our people.") is None
    assert facts.clearance("No security clearance required.") is None
    assert facts.clearance("Public Trust required.")["level"] == "public_trust"


def test_labels():
    f = facts.of({"description": "3+ years of experience required. Bachelor's degree or equivalent experience. "
                                 "Ability to obtain Secret clearance."})
    assert facts.labels(f) == ["3+ yrs", "Bachelor's or equivalent", "Secret clearance (can obtain)"]


def test_years_caution_in_the_quick_score():
    p = profile.clean({"target_titles": ["Analyst"], "years_experience": 2})
    r = scoring.score({"title": "Analyst", "description": "Requires 6+ years of experience."}, p)
    assert "Asks for 6+ years; your profile says 2" in r["cautions"]


def test_listing_filters():
    led = jobs.Ledger()
    led.add([{"source": "indeed", "kind": "item", **r} for r in [
        {"id": "a1", "title": "Analyst", "description": "5+ years of experience. Bachelor's degree required.",
         "pay_text": "$90,000 - $110,000 a year", "remote": "remote"},
        {"id": "b2", "title": "Analyst", "description": "1 year of experience. High school diploma. Active Secret clearance required.",
         "pay_text": "$25 an hour", "remote": "onsite"},
        {"id": "c3", "title": "Analyst", "description": "Bachelor's degree or equivalent experience. Ability to obtain a Secret clearance.",
         "remote": "hybrid"},
    ]], profile.clean({}))

    def ids(q):
        return sorted(r["id"] for r in led.listing(q))
    assert ids({"remote": "remote"}) == ["a1"]
    assert ids({"min_pay": "60000"}) == ["a1"]  # c3 lists no pay, b2 is $52,000
    assert ids({"max_years": "2"}) == ["b2", "c3"]  # c3 doesn't say, so it isn't ruled out
    assert ids({"degree": "high_school"}) == ["b2", "c3"]  # c3 accepts experience instead
    assert ids({"clearance": "none"}) == ["a1"]
    assert ids({"clearance": "obtainable"}) == ["a1", "c3"]
    assert [r["id"] for r in led.listing({"sort": "years"})] == ["b2", "a1", "c3"]
    assert "years_required" in led.csv().splitlines()[0]


def test_old_jobs_get_facts_on_load():
    store.write_json(jobs.FILE, {"jobs": {"indeed:z9": {"key": "indeed:z9", "source": "indeed", "id": "z9",
                                                        "description": "4 years of experience required."}}})
    assert jobs.Ledger().get("indeed:z9")["facts"]["years"]["required"] == 4
