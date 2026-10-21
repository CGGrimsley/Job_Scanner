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
