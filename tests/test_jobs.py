from job_scanner import jobs, profile

P = profile.clean({"target_titles": ["Data Analyst"], "skills": ["SQL"]})


def card(**kw):
    return {"source": "linkedin", "id": "1234567", "kind": "card", "title": "Data Analyst", "company": "Acme", **kw}


def test_card_then_posting_merge_into_one_record():
    L = jobs.Ledger()
    out = L.add([card()], P)
    assert out["added"] == 1 and out["marks"][0]["key"] == "linkedin:1234567"
    L.add([{"source": "linkedin", "id": "1234567", "kind": "item", "title": "Data Analyst", "description": "We need SQL " * 20}], P)
    L.add([card(title="Data Analyst (old card text)")], P)
    rec = jobs.Ledger().get("linkedin:1234567")
    assert rec["seen"] == 3 and rec["opened"]
    assert rec["title"] == "Data Analyst"  # a card doesn't overwrite what the posting said
    assert "SQL" in rec["description"]


def test_bad_rows_are_dropped():
    L = jobs.Ledger()
    out = L.add([{"source": "evil", "id": "1", "title": "x"}, {"source": "indeed", "id": "../../etc", "title": "x"},
                 {"source": "indeed", "id": "abc123def456", "kind": "card"}, "nope",
                 {"source": "indeed", "id": "abc123def456", "url": "javascript:alert(1)", "title": "ok"}], P)
    assert out["added"] == 1
    assert "url" not in L.get("indeed:abc123def456")


def test_status_tracking_and_listing():
    L = jobs.Ledger()
    L.add([card(), card(id="7654321", title="Barista")], P)
    rec = L.update("linkedin:1234567", {"status": "applied"})
    assert rec["applied_at"] and rec["history"][-1]["status"] == "applied"
    assert [r["key"] for r in L.listing({"status": "tracked"})] == ["linkedin:1234567"]
    assert L.listing({})[0]["key"] == "linkedin:1234567"  # best score first
    L.update("linkedin:7654321", {"status": "dismissed"})
    assert len(L.listing({})) == 1
    assert L.clear(keep_tracked=True) == 0  # both are tracked (dismissed counts)


def test_ai_analysis_wins_and_goes_stale():
    L = jobs.Ledger()
    L.add([card(description="x" * 200, kind="item")], P)
    fp = profile.fingerprint(P)
    L.set_analysis("linkedin:1234567", {"fit_score": 42, "verdict": "Skip", "summary": "Not a fit"}, fp)
    rec = L.get("linkedin:1234567")
    assert jobs.best(rec) == {"score": 42, "verdict": "Skip", "by": "ai"}
    assert jobs.ai_current(rec, fp)
    assert not jobs.ai_current(rec, "other")
    L.add([card(description="y" * 300, kind="item")], P)
    assert not jobs.ai_current(L.get("linkedin:1234567"), fp)


def test_csv_export():
    L = jobs.Ledger()
    L.add([card()], P)
    assert "Data Analyst" in L.csv().splitlines()[1]
