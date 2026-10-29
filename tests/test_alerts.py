from datetime import datetime, timedelta, timezone

import pytest

from job_scanner import alerts, jobs, profile, watch, web

P = profile.clean({"target_titles": ["Paralegal"], "skills": ["litigation", "e-filing"], "locations": ["Durham, NC"],
                   "remote": ["remote", "hybrid", "onsite"]})
TODAY = datetime.now(timezone.utc).date()


def rec(key="greenhouse:1", score=82, by="ai", verdict="Apply", posted_days=None, **extra):
    r = {"key": key, "source": key.split(":")[0], "id": key.split(":")[1], "title": "Paralegal", "company": "Acme Law",
         "location": "Durham, NC", "url": "https://job-boards.greenhouse.io/acme/jobs/1", "status": "",
         "first_seen": jobs.now_iso(), "rules": {"score": score if by == "rules" else 60, "verdict": verdict if by == "rules" else "Consider",
                                                 "pay_max": 55000}}
    if by == "ai":
        r["ai"] = {"fit_score": score, "verdict": verdict, "interview_odds": "Good odds: you meet every requirement."}
    if posted_days is not None:
        r["posted_on"] = (TODAY - timedelta(days=posted_days)).isoformat()
    r.update(extra)
    return r


def test_fresh_reads_the_posting_date_and_goes_stale_by_itself():
    assert jobs.fresh(rec(posted_days=0)) and jobs.fresh(rec(posted_days=1))
    assert not jobs.fresh(rec(posted_days=2)) and not jobs.fresh(rec())
    assert not jobs.fresh(rec(posted_days=0, closed=True))
    assert not jobs.fresh(rec(posted_days=0), today=TODAY + timedelta(days=3))


def test_which_jobs_reach_the_phone():
    assert alerts.worth_pushing(rec(score=75), 70)
    assert not alerts.worth_pushing(rec(score=65), 70)
    assert alerts.worth_pushing(rec(score=65, posted_days=0), 70)  # fresh: 10 points of slack
    assert not alerts.worth_pushing(rec(score=90, verdict="Consider"), 70)
    assert not alerts.worth_pushing(rec(score=90, status="applied"), 70)
    assert not alerts.worth_pushing(rec(score=90, pushed="2026-10-29T00:00:00+00:00"), 70)
    # without Claude's read, only a high quick score
    assert not alerts.worth_pushing(rec(score=75, by="rules"), 70)
    assert alerts.worth_pushing(rec(score=82, by="rules"), 70)


def test_job_alert_text():
    cfg = {"app_url": "https://jobs.example.com"}
    title, body, url, actions = alerts.job_alert(rec(posted_days=0, found_by="Acme Law (Greenhouse)"), cfg)
    assert title == "Apply 82 - Paralegal at Acme Law"
    assert "posted in the last day" in body and "up to $55,000" in body and "Good odds" in body and "Acme Law (Greenhouse)" in body
    assert url.startswith("https://job-boards.greenhouse.io/")
    assert actions[1] == ("In Job Scanner", "https://jobs.example.com/#job/greenhouse%3A1")
    _, body, _, _ = alerts.job_alert(rec(by="rules"), cfg)
    assert "Quick score only" in body


def test_push_sends_best_first_and_caps(monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "send", lambda cfg, title, *a, **k: sent.append(title))
    cfg = {"phone_topic": "jobs-abcdefgh", "phone_min": 70, "app_url": ""}
    recs = [rec(f"greenhouse:{i}", score=70 + i) for i in range(8)] + [rec("lever:x", score=50)]
    keys = alerts.push_jobs(recs, cfg)
    assert len(keys) == alerts.PER_RUN and keys[0] == "greenhouse:7" and "lever:x" not in keys
    assert alerts.push_jobs(recs, {"phone_topic": ""}) == []


def test_send_refuses_a_bad_topic():
    with pytest.raises(alerts.AlertError):
        alerts.send({"phone_topic": "x", "phone_server": "https://ntfy.sh"}, "t", "b")


def test_brief_due_once_a_day_after_the_hour():
    cfg = {"phone_topic": "jobs-abcdefgh", "brief_hour": 7}
    morning = datetime(2026, 10, 29, 7, 5)
    assert alerts.brief_due(morning, cfg, "")
    assert not alerts.brief_due(morning, cfg, "2026-10-29")
    assert not alerts.brief_due(morning.replace(hour=6), cfg, "")
    assert not alerts.brief_due(morning, {**cfg, "brief_hour": -1}, "")
    assert not alerts.brief_due(morning, {**cfg, "phone_topic": ""}, "")


def test_brief_lists_fresh_matches_todos_and_interviews():
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recs = [rec("greenhouse:1", score=80, posted_days=0), rec("lever:2", score=77),
            rec("lever:3", score=40, verdict="Skip", posted_days=0),
            rec("indeed:4", status="interviewing", interview_at=(TODAY + timedelta(days=1)).isoformat())]
    todo = [{"urgency": "now", "title": "Follow up", "title_job": "Legal Assistant"}, {"urgency": "soon", "title": "Later"}]
    title, body = alerts.brief(recs, todo, TODAY, since)
    assert title == "Morning: 1 fresh, 2 new to apply for, 1 to do, 1 interview"
    assert "Interview tomorrow: Paralegal at Acme Law" in body
    assert "Follow up: Legal Assistant" in body and "Later" not in body
    assert "Posted in the last day:\n- Apply 80" in body and "Apply 77" in body and "Skip" not in body
    assert alerts.brief([], [], TODAY, since) is None


def test_autosetup_watches_confirmed_boards_only():
    items = [{"name": "Acme Law", "watchable": {"provider": "greenhouse", "token": "acme", "jobs": 4, "guessed": False}},
             {"name": "Guessed Co", "watchable": {"provider": "lever", "token": "guessedco", "jobs": 2, "guessed": True}},
             {"name": "Duke", "board": "workday"}]
    assert watch.autosetup_due(watch.load(), P, watch.state())
    done = watch.autosetup(P, lambda places, titles, skills: items)
    assert done["watched"] == ["Acme Law"] and done["employers"] == 3
    cfg = watch.load()
    assert [b["token"] for b in cfg["boards"]] == ["acme"] and cfg["boards"][0]["auto"]
    assert not watch.autosetup_due(cfg, P, watch.state())  # done for these places
    assert watch.watch_confirmed(items) == []  # already watching
    moved = {**P, "locations": ["Raleigh, NC"]}
    assert not watch.autosetup_due(cfg, moved, watch.state())  # tried today: waits a day
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert watch.autosetup_due(cfg, moved, watch.state(), now=later)
    watch.save({"auto_boards": False})
    assert not watch.autosetup_due(watch.load(), moved, watch.state(), now=later)


def test_watching_checks_hourly_by_default():
    assert watch.load()["every_hours"] == 1


def test_phone_settings_and_brief_endpoint(monkeypatch):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(jobs.Ledger()))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert post("/api/settings", {"phone_topic": "no spaces allowed"})[0] == 400
        assert post("/api/settings", {"app_url": "javascript:alert(1)"})[0] == 400
        status, out = post("/api/settings", {"phone_topic": "jobs-abcdefgh", "phone_min": 150, "brief_hour": 8,
                                             "app_url": "https://jobs.example.com/"})
        assert status == 200 and out["settings"]["phone_min"] == 100 and out["settings"]["app_url"] == "https://jobs.example.com"
        sent = []
        monkeypatch.setattr(alerts, "send", lambda cfg, title, body, *a, **k: sent.append((title, body)))
        status, out = post("/api/alerts/brief", {})
        assert status == 200 and out["ok"] and not out["sent"] and not sent  # nothing to say yet
    finally:
        httpd.shutdown()


def test_watched_jobs_go_to_the_phone_once(monkeypatch):
    from job_scanner import store

    store.save_settings({"phone_topic": "jobs-abcdefgh"})
    ledger = jobs.Ledger()
    ledger.jobs["greenhouse:1"] = rec(posted_days=0)
    ledger.jobs["greenhouse:2"] = rec("greenhouse:2", score=40, verdict="Skip")
    sent = []
    monkeypatch.setattr(alerts, "send", lambda cfg, title, *a, **k: sent.append(title))
    handler = web.make_handler(ledger)
    handler.after_watch(["greenhouse:1", "greenhouse:2"])
    handler.after_watch(["greenhouse:1"])
    assert sent == ["Apply 82 - Paralegal at Acme Law"]
    assert ledger.get("greenhouse:1")["pushed"]
