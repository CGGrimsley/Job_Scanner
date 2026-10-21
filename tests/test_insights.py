from datetime import date

from job_scanner import insights, jobs, signals


def rec(**kw):
    base = {"key": "x:" + kw.get("id", "1"), "source": "indeed", "id": "1", "title": "Data Analyst", "company": "Acme"}
    base.update(kw)
    return base


def test_scam_signs_cap_the_score_even_over_claude():
    L = jobs.Ledger()
    L.add([{"source": "indeed", "id": "scam12345", "kind": "item", "title": "Data Entry Clerk", "company": "Acme",
            "description": "Remote data entry, no experience needed, $45/hr. We will send a check to purchase your home "
                           "office equipment from our vendor. Contact our HR on Telegram: @acmehr"}],
          {"target_titles": ["data entry clerk"], "skills": ["typing"]})
    r = L.get("indeed:scam12345")
    texts = [w["text"] for w in signals.warnings(r)]
    assert any("Telegram" in t for t in texts) and any("check" in t for t in texts)
    assert r["rules"]["score"] <= 30 and r["rules"]["verdict"] == "Skip"
    r["ai"] = {"fit_score": 85, "verdict": "Apply"}
    assert jobs.best(r) == {"score": 30, "verdict": "Skip", "by": "ai"}


def test_ghost_and_pay_transparency_signs():
    r = rec(location="Denver, CO", posted_text="Reposted 30+ days ago", description="x" * 900,
            rules={"pay_max": None, "age_days": 60})
    codes = {w["code"] for w in signals.warnings(r)}
    assert {"reposted", "old", "no_pay"} <= codes
    r2 = rec(location="Raleigh, NC", description="x" * 900, rules={"pay_max": None, "age_days": 3})
    assert signals.warnings(r2) == []  # NC has no pay-posting law
    assert signals.state_of("Remote in Washington") == "WA"


def test_the_same_job_on_two_sites_is_one_job_and_carries_your_status():
    L = jobs.Ledger()
    L.add([{"source": "linkedin", "id": "3900000001", "kind": "card", "title": "Data Analyst (Hybrid)", "company": "Acme Health, Inc.",
            "location": "Raleigh, NC"},
           {"source": "indeed", "id": "abcdef123456", "kind": "card", "title": "Data Analyst", "company": "Acme Health",
            "location": "Raleigh, NC 27601"},
           {"source": "indeed", "id": "abcdef999999", "kind": "card", "title": "Data Analyst", "company": "Acme Health",
            "location": "Charlotte, NC"}], {})
    L.update("linkedin:3900000001", {"status": "applied"})
    keys = [r["key"] for r in L.listing({})]
    assert "linkedin:3900000001" in keys and "indeed:abcdef123456" not in keys and "indeed:abcdef999999" in keys
    m = L.mark(L.get("indeed:abcdef123456"))
    assert m["status"] == "applied" and m["status_via"] == "LinkedIn"
    assert L.public(L.get("linkedin:3900000001"))["also_on"][0]["source"] == "Indeed"
    assert len(L.listing({"dupes": True})) == 3


def test_accuracy_counts_by_the_rating_at_apply_time_and_admits_small_samples():
    today = date(2026, 10, 21)
    recs = [rec(id=str(i), key=f"x:{i}", status="rejected", applied_at="2026-09-01",
                applied_score={"score": 75, "verdict": "Apply", "by": "ai"}) for i in range(3)]
    recs.append(rec(id="9", key="x:9", status="interviewing", applied_at="2026-09-01", history=[{"status": "applied"}],
                    applied_score={"score": 50, "verdict": "Consider", "by": "rules"}))
    recs.append(rec(id="8", key="x:8", status="applied", applied_at="2026-08-01", applied_score={"verdict": "Apply", "by": "ai"}))
    out = insights.accuracy(recs, today)
    apply = next(r for r in out["rows"] if r["verdict"] == "Apply")
    assert apply["applied"] == 4 and apply["rejected"] == 3 and apply["no_reply"] == 1 and apply["rate"] == 0
    assert "too few" in out["note"]


def test_skill_gaps_and_pay():
    profile = {"resumes": [{"name": "A", "text": "SQL and Excel reporting"}], "skills": ["Python"], "target_titles": ["data analyst"],
               "locations": ["Raleigh, NC"]}
    recs = [rec(id=str(i), key=f"x:{i}", status="saved", location="Raleigh, NC",
                rules={"pay_min": 60000 + i * 5000, "pay_max": 70000 + i * 5000},
                ai={"verdict": "Consider", "keywords": ["SQL", "Power BI", "Python"],
                    "gaps": [{"requirement": "3+ years of Power BI experience", "severity": "major"}]}) for i in range(6)]
    gaps = insights.skill_gaps(recs, profile)
    terms = {m["term"]: m for m in gaps["missing_keywords"]}
    assert "SQL" not in terms and terms["Power BI"]["jobs"] == 6 and terms["Python"]["on_skills_list"]
    assert gaps["gaps"][0]["jobs"] == 6
    pay = insights.pay_report(recs, profile)
    assert pay["titles"][0]["near"]["n"] == 6 and pay["titles"][0]["near"]["median"] == 77500
    pos = insights.pay_position(recs[5], recs)
    assert pos["enough"] and pos["percentile"] == 100
