import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from job_scanner import jobs, store, web


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(jobs.Ledger()))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_capture_needs_the_pairing_token(server):
    job = {"source": "indeed", "id": "abc123def456", "kind": "card", "title": "Data Analyst"}
    assert call(server + "/api/capture", {"jobs": [job]})[0] == 401
    status, out = call(server + "/api/capture", {"jobs": [job]}, {"X-Scanner-Token": store.pairing_token()})
    assert status == 200 and out["added"] == 1 and out["marks"][0]["verdict"]


def test_profile_round_trip_and_rescore(server):
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Data Analyst"}]},
         {"X-Scanner-Token": store.pairing_token()})
    status, out = call(server + "/api/profile", {"profile": {"target_titles": "Data Analyst", "skills": "SQL, Excel"}})
    assert status == 200 and out["profile"]["skills"] == ["SQL", "Excel"]
    _, state = call(server + "/api/state")
    assert state["profile"]["target_titles"] == ["Data Analyst"]
    _, listing = call(server + "/api/jobs")
    assert listing["jobs"][0]["rules"]["reasons"][0].startswith("Title matches")


def test_cross_site_posts_are_refused(server):
    status, _ = call(server + "/api/profile", {"profile": {}}, {"Origin": "https://evil.example"})
    assert status == 403


def test_rebinding_host_is_refused(server):
    req = urllib.request.Request(server + "/api/state", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 421


def test_analyze_without_claude_reports_why(server):
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "kind": "item", "title": "Data Analyst",
                                             "description": "SQL " * 50}]}, tok)
    call(server + "/api/profile", {"profile": {"target_titles": "Data Analyst"}})
    status, out = call(server + "/api/jobs/indeed%3Aabc123def456/analyze", {})
    assert status == 502 and "set up" in out["error"]
    status, out = call(server + "/api/capture/analyze", {"source": "indeed", "id": "abc123def456", "auto": True}, tok)
    assert status in (200, 502)


def test_job_tracking(server):
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Data Analyst"}]},
         {"X-Scanner-Token": store.pairing_token()})
    status, out = call(server + "/api/jobs/indeed:abc123def456/update", {"status": "applied", "follow_up": "2026-11-01"})
    assert status == 200 and out["job"]["status"] == "applied"
    assert call(server + "/api/jobs/indeed:abc123def456/update", {"follow_up": "soon"})[0] == 400
    assert call(server + "/api/jobs/nope:1")[0] == 404


def test_static_and_no_traversal(server):
    with urllib.request.urlopen(server + "/") as r:
        assert b"Job Scanner" in r.read()
    assert call(server + "/..%2f..%2fpyproject.toml")[0] == 404


def test_places_and_cover_letter_endpoints(server, monkeypatch):
    from job_scanner import ai
    _, out = call(server + "/api/places?q=Rale")
    assert out["places"][0] == "Raleigh, NC"
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Data Analyst"}]}, tok)
    status, out = call(server + "/api/capture/cover-letter", {"source": "indeed", "id": "abc123def456"}, tok)
    assert status == 400 and "résumé" in out["error"]
    call(server + "/api/profile", {"profile": {"resumes": [{"name": "Data", "text": "SQL"}]}})
    monkeypatch.setattr(ai, "cover_letter", lambda job, text, notes, name, tone: f"Letter from {name or 'best'} ({tone})")
    status, out = call(server + "/api/capture/cover-letter", {"source": "indeed", "id": "abc123def456"}, tok)
    assert status == 200 and out["letter"] == "Letter from best (standard)"
    status, out = call(server + "/api/jobs/indeed:abc123def456/cover-letter", {"resume": "Data", "tone": "warm"})
    assert out["job"]["cover_letter"] == {**out["job"]["cover_letter"], "text": "Letter from Data (warm)", "resume": "Data"}
    assert call(server + "/api/jobs/indeed:abc123def456/cover-letter", {"resume": "Nope"})[0] == 400


def test_tailor_message_export_and_todo(server, monkeypatch):
    from job_scanner import ai
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Data Analyst", "company": "Acme"}]}, tok)
    call(server + "/api/profile", {"profile": {"resumes": [{"name": "Data", "text": "Built 12 dashboards"}]}})
    monkeypatch.setattr(ai, "tailor_resume", lambda job, text, name: {
        "resume": "# Sam\n- Built 12 dashboards\n- Cut costs 30%", "changes": ["Moved dashboards up"], "left_out": ["Power BI"]})
    status, out = call(server + "/api/jobs/indeed:abc123def456/tailor", {})
    t = out["job"]["tailored"]
    assert status == 200 and t["check"] == ["Cut costs 30%"] and t["left_out"] == ["Power BI"]
    with urllib.request.urlopen(server + "/api/jobs/indeed:abc123def456/export?doc=resume&format=pdf") as r:
        assert r.read(5) == b"%PDF-" and "Resume%20-%20Acme" in r.headers["Content-Disposition"]
    assert call(server + "/api/jobs/indeed:abc123def456/export?doc=letter&format=pdf")[0] == 400  # no letter yet
    monkeypatch.setattr(ai, "draft_message", lambda job, text, kind, notes: {"subject": "Following up", "body": "Hi [Name]"})
    status, out = call(server + "/api/jobs/indeed:abc123def456/message", {"kind": "follow_up"})
    assert status == 200 and out["message"]["subject"] == "Following up"
    assert call(server + "/api/jobs/indeed:abc123def456/message", {"kind": "rant"})[0] == 400
    call(server + "/api/jobs/indeed:abc123def456/update", {"status": "applied"})
    _, out = call(server + "/api/todo")
    assert out["todo"][0]["id"] == "reach-out"
    call(server + "/api/jobs/indeed:abc123def456/update", {"done": "reach-out"})
    assert call(server + "/api/todo")[1]["todo"] == []


def test_easy_apply_builds_the_packet_and_autofill_finds_it(server, monkeypatch):
    from job_scanner import ai
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "greenhouse", "id": "acme-4012345", "kind": "item", "title": "Analyst",
                                             "company": "Acme", "description": "SQL",
                                             "url": "https://boards.greenhouse.io/acme/jobs/4012345"}]}, tok)
    call(server + "/api/profile", {"profile": {"name": "Sam Lee", "skills": "SQL",
                                               "resumes": [{"name": "Data", "text": "SQL reports"}, {"name": "Ops", "text": "Ops"}],
                                               "apply": {"email": "sam@example.com", "work_authorized": "yes", "linkedin": "linkedin.com/in/sam"}}})
    seen = {}

    def analyze_job(job, text, context="", **kw):
        return {"fit_score": 60, "qualification_score": 60, "confidence": "medium", "verdict": "Consider", "summary": "ok",
                "best_resume": "Data"}

    def tailor_resume(job, text, name):
        seen["tailor"] = name
        return {"resume": "# Sam\n- SQL reports", "changes": [], "left_out": []}

    def cover_letter(job, text, notes, name, tone):
        seen["letter"] = name
        return "Dear [Hiring Manager],"

    def answer_questions(job, text, facts, questions=None):
        seen["facts"] = facts
        return [{"question": "Why Acme?", "answer": "Your SQL work", "basis": "Data résumé"},
                {"question": "Years of Python?", "answer": "", "basis": "Not shown"}]

    for name, fn in (("analyze_job", analyze_job), ("tailor_resume", tailor_resume), ("cover_letter", cover_letter),
                     ("answer_questions", answer_questions)):
        monkeypatch.setattr(ai, name, fn)
    status, out = call(server + "/api/jobs/greenhouse:acme-4012345/easy-apply", {})
    j = out["job"]
    assert status == 200 and not out["errors"]
    assert seen["tailor"] == seen["letter"] == "Data"  # the assessment's pick, so letter and résumé agree
    assert "Legally authorized to work in the country of the job: Yes" in seen["facts"]
    assert j["status"] == "saved" and j["packet"]["resume"] == "Data" and len(j["answers"]["items"]) == 2

    # the application form, embedded on the company's own site with the Greenhouse id in its address
    status, fill = call(server + "/api/capture/autofill", {"url": "https://acme.com/careers?gh_jid=4012345"}, tok)
    assert status == 200 and fill["job"]["key"] == "greenhouse:acme-4012345"
    assert fill["fields"]["email"] == "sam@example.com" and fill["fields"]["first_name"] == "Sam"
    assert fill["fields"]["linkedin"] == "https://linkedin.com/in/sam"
    assert [a["question"] for a in fill["answers"]] == ["Why Acme?"]  # blank answers are left to the person
    assert fill["has_resume"] and fill["letter"]
    req = urllib.request.Request(server + "/api/capture/export?key=greenhouse:acme-4012345&doc=resume&format=pdf", headers=tok)
    with urllib.request.urlopen(req) as r:
        assert r.read(5) == b"%PDF-"
    assert call(server + "/api/capture/autofill", {"url": "https://acme.com/careers"})[0] == 401
    status, out = call(server + "/api/capture/answers", {"key": "greenhouse:acme-4012345", "questions": ["Why Acme?"]}, tok)
    assert status == 200 and out["answers"][0]["answer"] == "Your SQL work"


def test_models_company_read_and_site_health(server, monkeypatch):
    from job_scanner import ai
    status, out = call(server + "/api/settings", {"model_main": "opus", "model_light": "haiku", "model_auto": "light"})
    assert status == 200 and out["settings"]["model_main"] == "opus" and out["settings"]["model_auto"] == "light"
    assert call(server + "/api/settings", {"model_main": "gpt-9"})[0] == 400
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Analyst", "company": "Acme Corp"}]}, tok)
    asked = []
    monkeypatch.setattr(ai, "company_read", lambda job, **kw: asked.append(1) or
                        {"known": True, "summary": "Makes anvils.", "industry": "", "size": "", "notes": [], "check": []})
    status, out = call(server + "/api/jobs/indeed:abc123def456/company", {})
    assert status == 200 and out["company"]["summary"] == "Makes anvils."
    _, out = call(server + "/api/jobs/indeed:abc123def456")
    assert out["company"]["summary"] == "Makes anvils." and asked == [1]
    assert call(server + "/api/capture/health", {"source": "indeed", "what": "posting", "ok": False}, tok)[0] == 200
    _, state = call(server + "/api/state")
    assert state["site_health"]["indeed"]["posting"]["ok"] is False


def test_about_me_draft_endpoint(server, monkeypatch):
    from job_scanner import ai
    assert call(server + "/api/profile/about-me", {"resume": "too short"})[0] == 400
    monkeypatch.setattr(ai, "draft_about_me", lambda resumes, current, titles: {
        "about_me": "Operations coordinator for 3 years; cut costs 40%.", "to_add": ["What do you want next?"]})
    resume = "Operations Coordinator, Bluth Logistics, 3 years. Built weekly Excel reports for warehouse managers. " * 2
    status, out = call(server + "/api/profile/about-me", {"resume": resume, "about_me": "", "titles": "Operations Analyst"})
    assert status == 200 and out["to_add"] == ["What do you want next?"]
    assert out["check"] == ["Operations coordinator for 3 years; cut costs 40%."]  # 40 isn't in the résumé
    _, state = call(server + "/api/state")
    assert state["profile"]["about_me"] == ""  # a draft, not saved until they save the profile
