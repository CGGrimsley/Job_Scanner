import pytest

from job_scanner import feeds, jobs, mail, nearby, profile, store, watch

P = profile.clean({"target_titles": ["Paralegal"], "skills": ["litigation", "e-filing"], "locations": ["Durham, NC", "North Carolina"],
                   "remote": ["remote", "hybrid", "onsite"]})


def test_board_links():
    assert feeds.board_from_url("https://boards.greenhouse.io/acme/jobs/123") == ("greenhouse", "acme")
    assert feeds.board_from_url("https://job-boards.greenhouse.io/embed/job_board?for=acme") == ("greenhouse", "acme")
    assert feeds.board_from_url("https://jobs.lever.co/acme-co/abc") == ("lever", "acme-co")
    assert feeds.board_from_url("https://jobs.ashbyhq.com/Acme%20Labs") == ("ashby", "Acme Labs")
    assert feeds.board_from_url("https://careers.smartrecruiters.com/AcmeInc") == ("smartrecruiters", "AcmeInc")
    assert feeds.board_from_url("https://www.linkedin.com/jobs/view/1") is None


def fake_json(monkeypatch, answers):
    calls = []

    def get(url, headers=None):
        calls.append((url, headers))
        for part, data in answers.items():
            if part in url:
                if isinstance(data, Exception):
                    raise data
                return data
        raise feeds.FeedError(f"no fake for {url}")
    monkeypatch.setattr(feeds, "get_json", get)
    return calls


def test_boards_read_into_rows(monkeypatch):
    fake_json(monkeypatch, {
        "greenhouse.io/v1/boards/acme/jobs": {"jobs": [{"id": 7, "title": "Paralegal", "company_name": "Acme Law",
                                                        "location": {"name": "Durham, NC"}, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/7",
                                                        "content": "&lt;p&gt;Draft pleadings&lt;/p&gt;&lt;ul&gt;&lt;li&gt;e-filing&lt;/li&gt;&lt;/ul&gt;",
                                                        "first_published": "2026-10-20T10:00:00-04:00"}]},
        "api.lever.co": [{"id": "1b2c", "text": "Litigation Paralegal", "categories": {"location": "Raleigh, NC", "commitment": "Full-time"},
                          "hostedUrl": "https://jobs.lever.co/firm/1b2c", "descriptionPlain": "Support trial teams.",
                          "lists": [{"text": "Requirements", "content": "<li>2+ years</li>"}], "workplaceType": "hybrid",
                          "salaryRange": {"min": 55000, "max": 65000, "interval": "per-year-salary"}, "createdAt": 1760000000000}],
        "ashbyhq.com": {"jobs": [{"id": "a1", "title": "Legal Ops", "location": "Remote", "isRemote": True, "descriptionPlain": "x" * 50,
                                  "jobUrl": "https://jobs.ashbyhq.com/co/a1", "publishedAt": "2026-10-19", "isListed": True},
                                 {"id": "a2", "title": "Hidden", "isListed": False}]},
        "smartrecruiters.com/v1/companies/sr/postings/9": {"jobAd": {"sections": {"jobDescription": {"text": "<p>Full text</p>"}}}},
        "smartrecruiters.com/v1/companies/sr/postings": {"content": [{"id": "9", "name": "Paralegal", "location": {"city": "Durham", "region": "NC"},
                                                                      "ref": "https://api.smartrecruiters.com/v1/companies/sr/postings/9", "company": {"name": "SR Co"}}]},
    })
    gh = feeds.fetch_board("greenhouse", "acme")[0]
    assert gh["id"] == "7" and gh["company"] == "Acme Law" and gh["description"] == "Draft pleadings\n\n- e-filing"
    assert gh["posted_text"] == "2026-10-20"
    lv = feeds.fetch_board("lever", "firm", "The Firm")[0]
    assert lv["company"] == "The Firm" and lv["remote"] == "hybrid" and lv["pay_text"] == "$55,000 - $65,000 a year"
    assert "Requirements\n- 2+ years" in lv["description"]
    assert [r["id"] for r in feeds.fetch_board("ashby", "co")] == ["a1"]
    sr = feeds.fetch_board("smartrecruiters", "sr")[0]
    assert sr["kind"] == "item" and sr["description"] == "Full text" and sr["location"] == "Durham, NC"


def test_search_apis(monkeypatch):
    calls = fake_json(monkeypatch, {
        "usajobs.gov": {"SearchResult": {"SearchResultItems": [{"MatchedObjectId": "123", "MatchedObjectDescriptor": {
            "PositionTitle": "Paralegal Specialist", "OrganizationName": "Department of Justice", "PositionLocationDisplay": "Raleigh, NC",
            "PositionURI": "https://www.usajobs.gov/job/123", "PositionRemuneration": [{"MinimumRange": "51000", "MaximumRange": "66000", "RateIntervalCode": "PA"}],
            "UserArea": {"Details": {"JobSummary": "Support attorneys.", "MajorDuties": ["Research"]}}, "PublicationStartDate": "2026-10-18"}}]}},
        "adzuna.com": {"results": [{"id": 5, "title": "<strong>Paralegal</strong>", "company": {"display_name": "Firm"},
                                    "location": {"display_name": "Durham, NC"}, "redirect_url": "https://www.adzuna.com/land/ad/5",
                                    "salary_min": 50000, "salary_max": 60000, "salary_is_predicted": "1", "description": "Snippet"}]},
    })
    u = feeds.usajobs("KEY", "me@example.com", "paralegal", "Durham, NC", 25)[0]
    assert u["pay_text"] == "$51,000 - $66,000 a year" and "Duties:\n- Research" in u["description"]
    assert calls[0][1]["Authorization-Key"] == "KEY" and calls[0][1]["User-Agent"] == "me@example.com"
    a = feeds.adzuna("id", "key", "paralegal", "Durham, NC")[0]
    assert a["title"] == "Paralegal" and a["pay_min"] is None  # Adzuna's own salary estimate isn't passed off as the job's pay
    assert a["kind"] == "card"


LINKEDIN_ALERT = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x">Litigation Paralegal</a></td></tr>
<tr><td>Acme Law · Durham, NC</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345679/?trackingId=y">Legal Assistant</a></td></tr>
<tr><td>Bluth Legal</td></tr><tr><td>Raleigh, NC</td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search/?x=1">See all jobs</a></td></tr>
</table></body></html>"""
INDEED_ALERT = """<html><body>
<a href="https://www.indeed.com/rc/clk/dl?jk=0123456789abcdef&from=ja">Paralegal</a><div>Initech - Durham, NC</div><div>$22 - $26 an hour</div>
<a href="https://cts.indeed.com/v3/H4sIAAAA">Legal Secretary</a><div>Globex</div><div>Cary, NC</div>
</body></html>"""


def test_alert_emails():
    li = mail.parse_alert(LINKEDIN_ALERT, "linkedin")
    assert [(r["id"], r["title"], r["company"], r["location"]) for r in li] == [
        ("4012345678", "Litigation Paralegal", "Acme Law", "Durham, NC"), ("4012345679", "Legal Assistant", "Bluth Legal", "Raleigh, NC")]
    assert li[0]["url"] == "https://www.linkedin.com/jobs/view/4012345678/"
    ind = mail.parse_alert(INDEED_ALERT, "indeed")
    assert ind[0]["id"] == "0123456789abcdef" and ind[0]["company"] == "Initech" and ind[0]["pay_text"] == "$22 - $26 an hour"
    assert ind[1]["id"].startswith("m") and ind[1]["company"] == "Globex"  # no job id in the link: known by title and employer


def test_secrets_are_kept_and_never_shown():
    watch.save({"usajobs": {"enabled": True, "email": "me@example.com", "key": "SECRET"}})
    watch.save({"usajobs": {"key": ""}})  # left blank on the page: keep it
    cfg = watch.load()
    assert cfg["usajobs"]["key"] == "SECRET"
    shown = watch.public(cfg)
    assert "key" not in shown["usajobs"] and shown["usajobs"]["key_set"] is True and "SECRET" not in str(shown)


def test_a_run_keeps_local_matches_and_records_how_it_went(monkeypatch):
    watch.add_board("greenhouse", "acme", "Acme Law")
    watch.add_board("lever", "broken", "Broken Co")

    def fetch(provider, token, company="", want=None, details=25):
        if token == "broken":
            raise feeds.FeedError("api.lever.co answered 404")
        base = {"source": "greenhouse", "kind": "item", "company": company, "description": "Litigation paralegal, e-filing. " * 5}
        return [{**base, "id": "1", "title": "Paralegal", "location": "Durham, NC"},
                {**base, "id": "2", "title": "Paralegal", "location": "Austin, TX"},          # not one of their places
                {**base, "id": "3", "title": "Software Engineer", "location": "Durham, NC", "description": "Go and Kubernetes. " * 5}]
    monkeypatch.setattr(feeds, "fetch_board", fetch)
    led = jobs.Ledger()
    found = []
    st = watch.run(led, P, on_new=found.extend)
    assert set(led.jobs) == {"greenhouse:1"} and found == ["greenhouse:1"]
    assert led.get("greenhouse:1")["found_by"] == "Acme Law (Greenhouse)"
    gh, lv = st["sources"]["board:greenhouse:acme"], st["sources"]["board:lever:broken"]
    assert (gh["found"], gh["kept"], gh["added"], gh["ok"]) == (3, 1, 1, True)
    assert not lv["ok"] and "404" in lv["error"]
    assert watch.run(led, P)["sources"]["board:greenhouse:acme"]["added"] == 0  # nothing new the second time


def test_schedule_is_due():
    assert watch.due()
    store.write_json(watch.STATE, {"last_run": jobs.now_iso()})
    assert not watch.due()


def test_nearby_employers_are_checked(monkeypatch):
    boards = {("greenhouse", "acmelaw"): 12, ("lever", "bluthlegal"): 4}
    monkeypatch.setattr(nearby, "probe", lambda p, t: boards.get((p, t)))
    monkeypatch.setattr(nearby, "link_ok", lambda url: bool(url))
    named = nearby.check({"name": "Acme Law", "careers_url": "https://acme.example/careers", "board": "greenhouse", "board_token": "acmelaw"})
    assert named["watchable"] == {"provider": "greenhouse", "token": "acmelaw", "jobs": 12, "guessed": False} and named["link_ok"]
    guessed = nearby.check({"name": "Bluth Legal LLC", "careers_url": "", "board": "unknown", "board_token": ""})
    assert guessed["watchable"]["guessed"] is True and guessed["watchable"]["token"] == "bluthlegal"
    workday = nearby.check({"name": "Duke Health", "careers_url": "https://careers.example", "board": "workday", "board_token": ""})
    assert "watchable" not in workday  # no public feed: a link to open


def test_nearby_list_comes_from_claude(monkeypatch):
    from job_scanner import ai
    seen = {}

    def ask(system, prompt, schema, kind="other", **kw):
        seen["prompt"], seen["kind"] = prompt, kind
        return {"employers": [{"name": "Acme Law", "industry": "Legal", "why": "Big litigation group", "careers_url": "",
                               "board": "unknown", "board_token": "", "size": "large"}, {"name": "acme law", "industry": ""}]}
    monkeypatch.setattr(ai, "ask_json", ask)
    items = nearby.suggest(["Durham, NC"], ["Paralegal"], ["litigation"])
    assert [i["name"] for i in items] == ["Acme Law"] and "Durham, NC" in seen["prompt"] and seen["kind"] == "nearby"


@pytest.fixture
def server():
    import threading
    from http.server import ThreadingHTTPServer

    from job_scanner import web
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(jobs.Ledger()))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(url, body=None, headers=None):
    import json
    import urllib.request
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_watch_api(server, monkeypatch):
    assert call(server + "/api/watch/board", {"url": "https://example.com/careers"})[0] == 400
    monkeypatch.setattr(nearby, "probe", lambda p, t: 5 if t == "acme" else None)
    monkeypatch.setattr(feeds, "board_name", lambda p, t: "Acme Law")
    status, out = call(server + "/api/watch/board", {"url": "https://boards.greenhouse.io/acme"})
    assert status == 200 and out["jobs"] == 5 and out["config"]["boards"][0]["name"] == "Acme Law"
    assert call(server + "/api/watch/board", {"url": "https://jobs.lever.co/nope"})[0] == 400
    call(server + "/api/watch", {"email": {"enabled": True, "user": "me@example.com", "password": "app-pass"}})
    _, got = call(server + "/api/watch")
    assert got["config"]["email"]["password_set"] is True and "app-pass" not in str(got)
    assert call(server + "/api/capture/news")[0] == 401
    status, news = call(server + "/api/capture/news?since=", headers={"X-Scanner-Token": store.pairing_token()})
    assert status == 200 and news["news"] == []
    assert call(server + "/api/watch/nearby", {})[0] == 400  # no places on the profile yet


def test_only_the_strongest_new_finds_are_read_by_claude(monkeypatch):
    from job_scanner import ai, web
    profile.save({"target_titles": ["Paralegal"], "skills": ["litigation"], "locations": ["Durham, NC"]})
    led = jobs.Ledger()
    rows = [{"source": "greenhouse", "id": str(i), "kind": "item", "title": "Paralegal", "company": "Acme",
             "location": "Durham, NC", "description": "Litigation paralegal. " * 20} for i in range(8)]
    rows.append({**rows[0], "id": "99", "title": "Chef", "description": "Cook. " * 40})  # a weak match
    led.add(rows, profile.load())
    handler = web.make_handler(led)
    read = []
    monkeypatch.setattr(ai, "analyze_job", lambda rec, *a, **k: read.append(rec["key"]) or
                        {"fit_score": 60, "qualification_score": 60, "confidence": "medium", "verdict": "Consider", "summary": "s"})
    monkeypatch.setattr(ai, "company_read", lambda *a, **k: {"known": False})
    handler.read_new([f"greenhouse:{r['id']}" for r in rows])
    assert len(read) == web.READ_PER_RUN and "greenhouse:99" not in read
