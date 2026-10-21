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


def _job_with_profile(server):
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "kind": "item", "title": "Data Analyst",
                                             "description": "SQL " * 50}]}, tok)
    call(server + "/api/profile", {"profile": {"target_titles": "Data Analyst", "skills": "SQL"}})
    return tok


def test_auto_reads_pause_while_the_plan_limit_is_used_up(server, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from job_scanner import ai
    tok = _job_with_profile(server)
    monkeypatch.setattr(ai, "_paused", {"until": datetime.now(timezone.utc) + timedelta(hours=1), "resets": "3pm"})
    status, out = call(server + "/api/capture/analyze", {"source": "indeed", "id": "abc123def456", "auto": True}, tok)
    assert status == 200 and out["limited"] and "3pm" in out["skipped"]


def test_limit_error_is_a_429_with_the_reset_time(server, monkeypatch):
    from job_scanner import ai

    def used_up(*a, **k):
        raise ai.AILimitError("Your Claude plan's usage limit is used up for now; it resets 3pm.", "3pm")
    _job_with_profile(server)
    monkeypatch.setattr(ai, "analyze_job", used_up)
    status, out = call(server + "/api/jobs/indeed:abc123def456/analyze", {})
    assert status == 429 and out["limit"] and out["resets"] == "3pm"


def test_cancel_and_health_reports(server):
    tok = {"X-Scanner-Token": store.pairing_token()}
    status, out = call(server + "/api/capture/cancel", {"source": "indeed", "id": "abc123def456"}, tok)
    assert status == 200 and out["cancelled"] == 0
    report = {"source": "linkedin", "what": "posting", "ok": False, "path": "/jobs/view/1/"}
    assert call(server + "/api/capture/health", report)[0] == 401
    status, out = call(server + "/api/capture/health", report, tok)
    assert status == 200 and out["health"]["linkedin"]["posting"]["ok"] is False
    assert call(server + "/api/capture/health", {"source": "evil", "what": "posting"}, tok)[0] == 400
    _, state = call(server + "/api/state")
    assert state["site_health"]["linkedin"]["posting"]["path"] == "/jobs/view/1/"


def test_tracker_digest_and_settings(server):
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "title": "Data Analyst"}]}, tok)
    call(server + "/api/jobs/indeed:abc123def456/update", {"status": "applied", "applied_at": "2026-01-01", "follow_up": ""})
    _, tr = call(server + "/api/tracker")
    assert [j["key"] for j in tr["due"]] == ["indeed:abc123def456"] and tr["outcomes"]["applied"] == 1
    assert call(server + "/api/capture/due", headers=tok)[1]["count"] == 1
    assert call(server + "/api/capture/due")[0] == 401
    status, d = call(server + "/api/digest")
    assert status == 200 and "usage" in d
    status, out = call(server + "/api/settings", {"model_auto": "haiku", "follow_up_days": 5})
    assert status == 200 and out["settings"]["model_auto"] == "haiku" and out["settings"]["follow_up_days"] == 5
    assert call(server + "/api/settings", {"model_auto": "gpt"})[0] == 400


def test_tailor_and_employer_endpoints(server, monkeypatch):
    from job_scanner import ai
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "kind": "item", "title": "Data Analyst",
                                             "company": "Acme", "description": "SQL " * 50}]}, tok)
    status, out = call(server + "/api/jobs/indeed:abc123def456/tailor", {})
    assert status == 400 and "résumé" in out["error"]
    call(server + "/api/profile", {"profile": {"target_titles": "Data Analyst", "resume": "Analyst at Initech. Wrote SQL reports. " * 5}})
    monkeypatch.setattr(ai, "tailor_resume", lambda *a: {"summary": "ok", "missing": [], "rewrites": [], "keywords_present": [], "keywords_missing": []})
    status, out = call(server + "/api/jobs/indeed:abc123def456/tailor", {})
    assert status == 200 and out["job"]["tailoring"]["summary"] == "ok"
    monkeypatch.setattr(ai, "employer_read", lambda name, postings: {"employer_type": "direct employer", "summary": f"{len(postings)} read",
                                                                     "signals": [], "concerns": [], "verify": []})
    status, out = call(server + "/api/jobs/indeed:abc123def456/employer", {})
    assert status == 200 and out["job"]["employer"]["read"]["summary"] == "1 read"
    _, listing = call(server + "/api/jobs")
    assert listing["jobs"][0]["employer"]["name"] == "Acme"


def test_listing_filters_over_http(server):
    tok = {"X-Scanner-Token": store.pairing_token()}
    call(server + "/api/capture", {"jobs": [{"source": "indeed", "id": "abc123def456", "kind": "item", "title": "Analyst",
                                             "description": "8+ years of experience required. " * 5}]}, tok)
    assert call(server + "/api/jobs?max_years=3")[1]["total"] == 0
    assert call(server + "/api/jobs?max_years=10")[1]["jobs"][0]["fact_tags"] == ["8+ yrs"]
