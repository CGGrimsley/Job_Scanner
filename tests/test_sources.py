import json

from job_scanner import feeds, jobs, signals, store, watch

SITEMAP = """<?xml version="1.0"?><sitemapindex><sitemap><loc>https://www.jobs.now/sitemap-general.xml</loc></sitemap>
<sitemap><loc>https://www.jobs.now/sitemap-jobs-1.xml</loc></sitemap></sitemapindex>"""
JOBS = """<urlset><url><loc>https://www.jobs.now/jobs/782057644-data-analyst</loc></url>
<url><loc>https://www.jobs.now/jobs/782057700-paralegal-ref-ab12</loc></url>
<url><loc>https://www.jobs.now/jobs/782057701-senior-trader-ref-77</loc></url>
<url><loc>https://www.jobs.now/companies/acme-1</loc></url></urlset>"""


def page(title, valid="2099-01-01T00:00:00Z"):
    data = {"@context": "https://schema.org/", "@type": "JobPosting", "title": title, "description": "<p>Draft pleadings.</p><ul><li>e-filing</li></ul>",
            "datePosted": "2026-10-24", "validThrough": valid, "employmentType": "FULL_TIME",
            "hiringOrganization": {"@type": "Organization", "name": "Acme Law &amp; Co"},
            "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Durham", "addressRegion": "NC"}}],
            "baseSalary": {"@type": "MonetaryAmount", "currency": "USD", "value": {"minValue": 55000, "maxValue": 55000, "unitText": "YEAR"}}}
    return ('<script type="application/ld+json">{"@type":"WebPage"}</script>'
            f'<script type="application/ld+json">{json.dumps(data)}</script>')


def fake_get(pages):
    calls = []

    def get(url, accept=""):
        calls.append(url)
        return pages[url]
    return get, calls


def test_jobsnow_reads_sitemap_then_only_wanted_new_pages():
    get, calls = fake_get({"https://www.jobs.now/sitemap.xml": SITEMAP, "https://www.jobs.now/sitemap-jobs-1.xml": JOBS,
                           "https://www.jobs.now/jobs/782057700-paralegal-ref-ab12": page("Paralegal [REF AB12]")})
    listing = feeds.jobsnow_listing(get)
    assert [j["slug_title"] for j in listing] == ["data analyst", "paralegal", "senior trader"]
    slept = []
    rows = feeds.jobsnow(lambda t: "paralegal" in t, {"782057644"}, get=get, sleep=slept.append)
    assert len(rows) == 1 and slept == [feeds.JOBSNOW_DELAY]
    r = rows[0]
    assert r["title"] == "Paralegal [REF AB12]" and r["company"] == "Acme Law & Co" and r["location"] == "Durham, NC"
    assert r["pay_text"] == "$55,000 a year" and r["description"].startswith("Draft pleadings.") and "- e-filing" in r["description"]
    assert r["job_type"] == "full time" and not r["closed"] and jobs.clean_row(r)["source"] == "jobsnow"
    assert "https://www.jobs.now/sitemap-general.xml" not in calls  # only the job sitemaps


def test_jobsnow_marks_expired_postings_closed():
    r = feeds.jobsnow_posting(page("Paralegal", valid="2020-01-01T00:00:00Z"), "https://www.jobs.now/jobs/1-p", "1")
    assert r["closed"]
    assert feeds.jobsnow_posting("<html>no data</html>", "u", "1") is None


def test_jobsnow_postings_carry_an_honest_caution():
    codes = [w["code"] for w in signals.warnings({"source": "jobsnow", "title": "Paralegal", "rules": {}})]
    assert "perm_ad" in codes


def test_usajobs_uses_a_key_from_the_environment(monkeypatch):
    p = {"target_titles": ["Paralegal"], "locations": ["Durham, NC"]}
    assert not [s for s in watch.sources(watch.load(), p) if s[0] == "usajobs"]
    monkeypatch.setenv("USAJOBS_API_KEY", "secret-key")
    monkeypatch.setenv("USAJOBS_EMAIL", "me@example.com")
    cfg = watch.load()
    assert [s for s in watch.sources(cfg, p) if s[0] == "usajobs"]
    pub = watch.public(cfg)["usajobs"]
    assert pub["key_from_env"] and pub["enabled"] and pub["email"] == "me@example.com" and "secret-key" not in json.dumps(pub)
    watch.save({"searches": {"keywords": "Paralegal"}})
    assert "secret-key" not in store.path(watch.FILE).read_text()  # never written to watch.json
    watch.save({"usajobs": {"enabled": False}})  # turned off here: stays off
    assert not [s for s in watch.sources(watch.load(), p) if s[0] == "usajobs"]


def test_jobsnow_source_is_off_until_chosen_and_remembers_what_it_read(monkeypatch):
    p = {"target_titles": ["Paralegal"], "locations": ["Durham, NC"]}
    assert not [s for s in watch.sources(watch.load(), p) if s[0] == "jobsnow"]
    watch.save({"jobsnow": {"enabled": True}})
    picked = []

    def fake(pick, known, **k):
        picked.append((pick("paralegal"), pick("senior trader"), known))
        return [{"source": "jobsnow", "id": "9", "kind": "item", "title": "Paralegal", "company": "Acme", "location": "Seattle, WA",
                 "url": "https://www.jobs.now/jobs/9-paralegal", "description": "x"}]
    monkeypatch.setattr(feeds, "jobsnow", fake)
    led = jobs.Ledger()
    watch.run(led, p, only="jobsnow")
    assert picked[0][:2] == (True, False)
    assert "jobsnow:9" not in led.jobs  # not in their places
    assert watch.state()["jobsnow_seen"] == ["9"]
    watch.run(led, p, only="jobsnow")
    assert "9" in picked[1][2]  # not read again
