from datetime import date

from job_scanner import advice, docx, pdf, resume

TODAY = date(2026, 10, 21)


def ids(rec):
    return [n["id"] for n in advice.nudges(rec, TODAY)]


def test_applied_timeline():
    rec = {"status": "applied", "applied_at": "2026-10-19"}
    assert ids(rec) == ["reach-out"]
    assert "follow-up-1" in ids({**rec, "applied_at": "2026-10-12"})
    assert "follow-up-2" in ids({**rec, "applied_at": "2026-10-04"})
    assert "stale" in ids({**rec, "applied_at": "2026-09-01"})
    assert "reach-out" not in ids({**rec, "contact": "Jane, recruiter"})


def test_interview_and_done():
    rec = {"status": "interviewing", "interview_at": "2026-10-21"}
    n = advice.nudges(rec, TODAY)
    assert n[0]["id"] == "thanks-2026-10-21" and n[0]["message"] == "thank_you"
    assert ids({**rec, "done": ["thanks-2026-10-21"]}) == []
    assert ids({**rec, "interview_at": "2026-10-24"})[0].startswith("prep-")
    assert ids({"status": "interviewing"}) == ["interview-date"]


def test_saved_and_reminders():
    assert ids({"status": "saved", "posted_text": "3 weeks ago"}) == ["apply-soon"]
    assert ids({"status": "saved", "closed": True}) == ["closed"]
    assert ids({"status": "offer", "follow_up": "2026-10-20"}) == ["reminder-2026-10-20", "offer"]
    assert ids({"status": "rejected", "follow_up": "2026-10-20"}) == []
    todo = advice.todo([{"key": "a", "status": "applied", "applied_at": "2026-10-19"},
                        {"key": "b", "status": "offer"}], TODAY)
    assert [t["key"] for t in todo] == ["b", "a"]  # most urgent first


def test_pdf_and_docx_exports():
    text = "# Sam Rivera\n## Experience\n- Built dashboards (Tableau) — 12 departments, résumé\n" + "- Line\n" * 120
    out = pdf.from_text(text)
    assert out.startswith(b"%PDF-1.4") and out.rstrip().endswith(b"%%EOF")
    assert b"/Count 3" in out or b"/Count 2" in out  # it runs onto more pages
    assert b"\\(Tableau\\)" in out
    assert pdf.from_text("Dear [Hiring Manager],\n\nThanks.", letter=True).count(b"/Type /Page ") == 1
    assert resume.docx_text(docx.from_text(text)).splitlines()[:3] == ["Sam Rivera", "EXPERIENCE", "•\tBuilt dashboards (Tableau) — 12 departments, résumé"]
