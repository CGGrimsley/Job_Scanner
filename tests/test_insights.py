from datetime import date, datetime, timedelta, timezone

import pytest

from job_scanner import ai, companies, groups, jobs, profile, store, tracking

P = profile.clean({"target_titles": ["Data Analyst"], "skills": ["SQL"]})


def add(led, *rows):
    return led.add([{"kind": "card", **r} for r in rows], P)


def test_names_match_across_sites():
    assert groups.company_key("Acme Corp.") == groups.company_key("ACME, Inc") == "acme"
    assert groups.company_key("AT&T") == groups.company_key("AT and T")
    assert groups.title_key("Sr. Data Analyst (Hybrid)") == groups.title_key("Senior Data Analyst - Remote")
    assert groups.city_of("Raleigh, NC 27601") == groups.city_of("Raleigh, NC (Hybrid)") == "raleigh"


def test_same_job_on_two_sites_is_listed_once():
    led = jobs.Ledger()
    add(led, {"source": "linkedin", "id": "4012345678", "title": "Data Analyst", "company": "Acme Corp", "location": "Raleigh, NC (Hybrid)"},
        {"source": "indeed", "id": "0123456789abcdef", "title": "Data Analyst", "company": "Acme, Inc.", "location": "Raleigh, NC 27601"},
        {"source": "indeed", "id": "fedcba9876543210", "title": "Data Analyst", "company": "Acme", "location": "Austin, TX"})
    assert len(led.listing({})) == 2  # Austin is a different job
    assert len(led.listing({"dupes": "1"})) == 3
    li = led.get("linkedin:4012345678")
    assert [c["source"] for c in led.public(li)["copies"]] == ["indeed"]
    led.update("indeed:0123456789abcdef", {"status": "applied"})
    m = led.mark(li)
    assert m["status"] == "applied" and m["status_on"] == "Indeed"
    assert led.public(li)["copy_status"] == {"status": "applied", "on": "Indeed"}
    assert "linkedin:4012345678" not in [r["key"] for r in led.listing({"status": "untracked", "dupes": "1"})]


def test_reposts_are_flagged():
    led = jobs.Ledger()
    add(led, {"source": "indeed", "id": "0123456789abcdef", "title": "Data Analyst", "company": "Acme"})
    led.get("indeed:0123456789abcdef")["first_seen"] = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(timespec="seconds")
    add(led, {"source": "indeed", "id": "fedcba9876543210", "title": "Data Analyst", "company": "Acme"})  # relisted under a new id
    rec = led.get("indeed:fedcba9876543210")
    assert rec["repost"]["count"] == 1
    assert any(c.startswith("Reposted once") for c in rec["rules"]["cautions"])
    assert "reposted 1 time" in ai.posting_text(rec)


def test_a_posting_date_that_jumps_forward_is_a_repost():
    led = jobs.Ledger()
    add(led, {"source": "linkedin", "id": "4012345678", "title": "Data Analyst", "company": "Acme", "posted_text": "3 days ago"})
    led.get("linkedin:4012345678")["posted_on"] = (date.today() - timedelta(days=30)).isoformat()
    add(led, {"source": "linkedin", "id": "4012345678", "title": "Data Analyst", "company": "Acme", "posted_text": "1 day ago"})
    assert led.get("linkedin:4012345678")["repost"]["count"] == 1
    add(led, {"source": "linkedin", "id": "4012345679", "title": "BI Analyst", "company": "Acme", "posted_text": "Reposted 2 days ago"})
    assert led.get("linkedin:4012345679")["repost"]["count"] == 1


def test_applying_sets_a_follow_up_and_keeps_the_dates():
    store.save_settings({"follow_up_days": 7})
    led = jobs.Ledger()
    add(led, {"source": "indeed", "id": "0123456789abcdef", "title": "Data Analyst"})
    # the job page's form sends its blank date fields along with the status
    rec = led.update("indeed:0123456789abcdef", {"status": "applied", "applied_at": "", "follow_up": "", "notes": ""})
    assert rec["applied_at"] == date.today().isoformat()
    assert rec["follow_up"] == (date.today() + timedelta(days=7)).isoformat()
    assert rec["applied_score"] == jobs.best(rec)["score"]


def test_follow_ups_due():
    old = {"key": "a", "status": "applied", "applied_at": (date.today() - timedelta(days=12)).isoformat()}
    fresh = {"key": "b", "status": "applied", "applied_at": date.today().isoformat()}
    set_date = {"key": "c", "status": "interviewing", "follow_up": date.today().isoformat()}
    closed = {"key": "d", "status": "rejected", "follow_up": "2020-01-01"}
    assert [r["key"] for r in tracking.due([old, fresh, set_date, closed])] == ["a", "c"]  # longest overdue first


def test_results_by_score():
    def app(score, *statuses):
        return {"applied_at": "2026-10-01", "applied_score": score, "status": statuses[-1],
                "history": [{"status": s} for s in statuses]}
    few = tracking.outcomes([app(85, "applied", "interviewing")])
    assert few["applied"] == 1 and "9 more" in few["note"]
    recs = [app(85, "applied", "interviewing")] * 4 + [app(72, "applied", "interviewing", "offer")] + \
        [app(50, "applied", "rejected")] * 5 + [app(30, "applied")] * 2
    out = tracking.outcomes(recs)
    by = {b["band"]: b for b in out["bands"]}
    assert by["80+"]["interviews"] == 4 and by["70-79"]["offers"] == 1 and by["40-54"]["rejected"] == 5
    assert out["note"] == "4 of your 5 interviews came from jobs scored 80 or more."


def test_week_in_review():
    led = jobs.Ledger()
    add(led, {"source": "indeed", "id": "0123456789abcdef", "title": "Data Analyst", "company": "Acme"},
        {"source": "indeed", "id": "fedcba9876543210", "title": "Cook", "company": "Diner"})
    led.update("indeed:fedcba9876543210", {"status": "applied"})
    d = tracking.digest(led, {"week": {"calls": 3, "tokens": 100}})
    assert d["new_jobs"] == 2
    assert [j["key"] for j in d["best_unapplied"]] == ["indeed:0123456789abcdef"]
    assert [j["key"] for j in d["applied"]] == ["indeed:fedcba9876543210"]


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setattr(ai, "backend", lambda: "cli")
    answers = {}

    def fake(system, prompt, schema, kind, files, model=""):
        answers.setdefault("calls", []).append({"kind": kind, "model": model, "prompt": prompt})
        return answers[kind]
    monkeypatch.setattr(ai, "_cli", fake)
    return answers


def test_tailoring_drops_made_up_rewrites(claude):
    resume = "Operations coordinator, 2021-2024\n- Built weekly Excel reports for 4 warehouse managers\n- Answered vendor billing questions"
    claude["tailor"] = {"summary": "s", "missing": [], "keywords_present": [], "keywords_missing": [], "rewrites": [
        {"original": "Built weekly Excel reports for 4 warehouse managers", "suggested": "Produced weekly Excel reporting for 4 operations managers", "why": "w"},
        {"original": "Built weekly Excel reports for 4 warehouse managers", "suggested": "Built Excel reports that cut costs 20%", "why": "w"},
        {"original": "Led a team of 12 analysts", "suggested": "Led 12 analysts", "why": "w"}]}
    out = ai.tailor_resume({"title": "Analyst", "description": "Excel reporting"}, "Resume: ...", resume)
    assert [r["suggested"] for r in out["rewrites"]] == ["Produced weekly Excel reporting for 4 operations managers"]


def test_employer_read_and_models(claude):
    store.save_settings({"model_auto": "haiku", "model_ondemand": "opus"})
    claude["employer"] = {"employer_type": "something odd", "summary": "s", "signals": [], "concerns": [], "verify": []}
    out = ai.employer_read("Acme", [{"title": "Analyst", "description": "Our client, a Fortune 500 company..."}])
    assert out["employer_type"] == "unclear"
    assert claude["calls"][-1]["model"] == "opus"
    claude["analyze"] = {"fit_score": 50, "qualification_score": 50, "confidence": "high", "verdict": "Consider"}
    ai.analyze_job({"title": "x", "employer": {"read": {"employer_type": "staffing or recruiting agency", "summary": "Agency."}}}, "y", auto=True)
    assert claude["calls"][-1]["model"] == "haiku"
    assert "staffing or recruiting agency" in claude["calls"][-1]["prompt"]


def test_model_reaches_claude_code(monkeypatch):
    import json
    import subprocess
    monkeypatch.setenv("JOB_SCANNER_AI", "cli")
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/claude")
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"structured_output": {"ok": True}}), stderr="")
    monkeypatch.setattr(ai.subprocess, "run", run)
    store.save_settings({"model_ondemand": "sonnet"})
    ai.ask_json("s", "p", {})
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "sonnet"


def test_employer_store():
    companies.save("Acme Corp", {"employer_type": "direct employer"}, 2)
    assert companies.get("ACME, Inc.")["postings"] == 2
