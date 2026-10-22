from urllib.parse import parse_qs, urlparse

from job_scanner import discover, jobs, learn, resume_check, store


def test_search_links_are_fresh_and_leave_out_avoid_words():
    ls = discover.links("Paralegal", "Durham, NC", ["hybrid", "onsite"], ["commission only"])
    li = parse_qs(urlparse(ls[0]["url"]).query)
    assert ls[0]["site"] == "LinkedIn" and li["f_TPR"] == ["r86400"] and li["sortBy"] == ["DD"] and li["f_WT"] == ["3,1"]
    assert li["keywords"] == ['Paralegal NOT "commission only"'] and li["location"] == ["Durham, NC"]
    ind = parse_qs(urlparse(ls[2]["url"]).query)
    assert ind["fromage"] == ["1"] and ind["q"] == ['Paralegal -"commission only"'] and ind["radius"] == ["25"]
    remote = parse_qs(urlparse(discover.links("Analyst", "", ["remote"])[2]["url"]).query)
    assert remote["l"] == ["Remote"]
    rows = discover.for_profile({"target_titles": ["Paralegal"], "locations": ["Durham, NC", "Raleigh, NC"]}, ["Legal Assistant"])
    assert [(r["title"], r["place"]) for r in rows][:3] == [("Paralegal", "Durham, NC"), ("Paralegal", "Raleigh, NC"), ("Legal Assistant", "Durham, NC")]


def _rec(i, company, title, status):
    return {"key": f"indeed:{i}", "source": "indeed", "company": company, "title": title, "status": status,
            "rules": {"score": 80, "verdict": "Apply", "cautions": [], "level": "mid", "remote": "hybrid"}}


def test_learning_from_passes_needs_a_pattern_and_your_yes():
    p = {"target_titles": ["Paralegal"]}
    recs = [_rec(i, "Acme Staffing", "Paralegal", "dismissed") for i in range(3)] + [_rec(9, "Duke Health", "Paralegal", "saved")]
    sug = learn.suggestions(recs, p)
    assert [s["id"] for s in sug] == ["company:acme staffing"] and sug[0]["passed"] == 3
    fresh = _rec(20, "Acme Staffing, Inc.", "Paralegal", "")
    learn.apply(fresh)
    assert fresh["rules"]["score"] == 80  # nothing changes until approved
    learn.decide("company:acme staffing", True, "jobs at Acme Staffing")
    learn.apply(fresh)
    assert fresh["rules"]["score"] == 80 - learn.PENALTY and fresh["rules"]["cautions"][0].startswith("You usually pass on jobs at Acme")
    assert learn.suggestions(recs, p) == []  # not suggested twice
    learn.forget("company:acme staffing")
    assert learn.load()["rules"] == []
    learn.decide("company:acme staffing", False)
    assert learn.suggestions(recs, p) == []  # a "no" is remembered


def test_resume_check():
    good = ("Jordan Lee\njordan@example.com | (919) 555-0100\nExperience\n- Drafted 40+ pleadings a month at Smith Law, 2021-2024\n"
            "- Cut filing errors 30% by building a checklist\n- Managed 120 active case files\n- Calendared deadlines\n- Prepared exhibits\n"
            "Education\nB.A. English, 2020\nSkills\nWestlaw, Clio, e-filing\n" + "Handled discovery and client intake for litigation teams. " * 30)
    r = resume_check.check({"name": "Main", "text": good}, [{"term": "Westlaw", "jobs": 3}, {"term": "Relativity", "jobs": 1}])
    assert r["fix"] == [] and r["score"] == 100 and [k["term"] for k in r["keywords"]] == ["Westlaw"]
    bad = resume_check.check({"name": "Old", "text": "Objective: a job.\nI did things."})
    assert r["name"] == "Main" and bad["score"] < 30 and any("email" in f for f in bad["fix"])


def test_backup_keeps_two_weeks():
    store.write_json("jobs.json", {"jobs": {}})
    for d in range(1, 18):
        assert store.backup(f"2026-10-{d:02d}") is not None
    assert store.backup("2026-10-17") is None  # once a day
    kept = sorted(p.name for p in (store.data_dir() / "backups").iterdir())
    assert len(kept) == store.BACKUP_KEEP and kept[0] == "2026-10-04" and (store.data_dir() / "backups" / "2026-10-17" / "jobs.json").exists()


def test_rescore_applies_learned_rules():
    learn.decide("agency:yes", True, "staffing agency postings")
    rec = {"key": "indeed:1", "source": "indeed", "id": "1", "title": "Paralegal", "description": "Our client is a law firm. " * 10}
    jobs.rescore(rec, {"target_titles": ["Paralegal"]})
    assert any(c.startswith("You usually pass on staffing") for c in rec["rules"]["cautions"])
