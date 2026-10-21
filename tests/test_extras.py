from datetime import date, datetime, timezone

from job_scanner import insights, jobs, signals


def test_relisted_under_a_new_id_a_week_later():
    a = {"source": "indeed", "first_seen": "2026-10-01T10:00:00+00:00"}
    b = {"source": "indeed", "first_seen": "2026-10-12T10:00:00+00:00"}
    other_site = {"source": "linkedin", "first_seen": "2026-10-13T10:00:00+00:00"}
    assert signals.relisted([a, b, other_site]) == {"count": 1, "since": "2026-10-01"}
    assert signals.relisted([a, other_site]) is None  # another site isn't a repost
    rec = {**b, "title": "Analyst", "company": "Acme", "rules": {}}
    codes = [w["code"] for w in signals.warnings(rec, [a])]
    assert "reposted" in codes and "lingering" not in codes


def test_posting_date_jumping_forward_counts_as_a_repost():
    rec = {"rules": {"age_days": 3}}
    jobs.note_posted(rec, date(2026, 10, 1))
    assert rec["posted_on"] == "2026-09-28" and not rec.get("reposts")
    rec["rules"]["age_days"] = 1
    jobs.note_posted(rec, date(2026, 10, 3))  # posted 10-02: only 4 days later, just the site's rounding
    assert not rec.get("reposts")
    rec["rules"]["age_days"] = 0
    jobs.note_posted(rec, date(2026, 10, 20))
    assert rec["reposts"] == 1 and signals.relisted([{**rec, "source": "x"}])["count"] == 1


def test_weekly_review():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    recs = [
        {"key": "a:1", "source": "indeed", "title": "Analyst", "first_seen": "2026-10-20T00:00:00+00:00", "status": "",
         "rules": {"score": 82, "verdict": "Apply"}},
        {"key": "a:2", "source": "indeed", "title": "Clerk", "first_seen": "2026-09-01T00:00:00+00:00", "status": "interviewing",
         "applied_at": "2026-10-18", "rules": {"score": 60, "verdict": "Consider"},
         "history": [{"at": "2026-10-18T00:00:00+00:00", "status": "applied"}, {"at": "2026-10-20T00:00:00+00:00", "status": "interviewing"}]},
    ]
    w = insights.weekly(recs, now, [{"urgency": "now", "title": "Say thank you", "key": "a:2"}, {"urgency": "soon"}], {"week": {"calls": 3}})
    assert w["new_jobs"] == 1 and w["new_matches"] == 1 and w["best_unapplied"][0]["key"] == "a:1"
    assert w["sent"][0]["key"] == "a:2" and w["moved"][0]["status"] == "interviewing"
    assert len(w["due"]) == 1 and w["usage"]["week"]["calls"] == 3
