"""The extension's page readers against saved sample pages (tests/fixtures). Needs Node and Playwright; skipped
without them. When a site changes, save a fresh copy of the page as a fixture and fix capture.js until this passes."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).parent / "extension" / "readers.mjs"


@pytest.fixture(scope="module")
def reads():
    if not shutil.which("node"):
        pytest.skip("Node isn't installed")
    proc = subprocess.run(["node", str(RUNNER)], capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        if "Cannot find module" in proc.stderr or "Executable doesn't exist" in proc.stderr:
            pytest.skip("Playwright isn't installed (npm i -g playwright)")
        raise AssertionError(proc.stderr[-2000:])
    return json.loads(proc.stdout)


def by_kind(page, kind):
    return [j for j in page["jobs"] if j["kind"] == kind]


def test_linkedin_cards_and_open_posting(reads):
    p = reads["linkedin.html"]
    cards = by_kind(p, "card")
    assert [c["id"] for c in cards] == ["4012345678", "4098765432"]
    assert cards[0]["company"] == "Acme Health" and cards[0]["pay_text"] == "$65K/yr - $80K/yr"
    item = by_kind(p, "item")[0]
    assert item["title"] == "Data Analyst" and "SQL and Tableau" in item["description"]
    assert [h for h in p["health"] if not h["ok"]] == []
    assert {h["what"] for h in p["health"]} == {"cards", "posting"}  # each reported readable once


def test_indeed_and_ncworks_cards(reads):
    indeed = by_kind(reads["indeed.html"], "card")
    assert indeed[0]["title"] == "Junior Data Analyst" and indeed[0]["company"] == "City of Durham"
    nc = by_kind(reads["ncworks.html"], "card")
    assert [c["title"] for c in nc] == ["Business Analyst", "Line Cook"] and nc[1]["pay_text"] == "$15 per hour"


def test_career_page_json_ld(reads):
    item = by_kind(reads["greenhouse.html"], "item")[0]
    assert item["company"] == "Acme Health" and item["pay_text"].startswith("$65,000") and "Bachelor" in item["description"]


def test_a_changed_page_is_reported_not_silently_missed(reads):
    p = reads["linkedin-changed.html"]
    assert by_kind(p, "item") == []
    bad = [h for h in p["health"] if not h["ok"]]
    assert bad and bad[0]["problem"] == "Can't read this posting" and bad[0]["what"] == "posting"


def test_linkedin_newer_layout(reads):
    p = reads["linkedin-new.html"]
    cards = {c["id"]: c for c in by_kind(p, "card")}
    assert set(cards) == {"4457298164", "4457311111"}
    assert cards["4457298164"]["title"] == "Data Analyst" and cards["4457298164"]["company"] == "Acme Health"
    item = by_kind(p, "item")[0]
    assert item["id"] == "4457298164" and item["title"] == "Data Analyst" and item["company"] == "Acme Health"
    assert "Tableau" in item["description"] and not item["description"].startswith("About the job")
    assert item["location"] == "Raleigh, NC" and item["applicants"] == 100
    assert p["diag"]["structure"]["items_with_one_id"] == 2 and p["diag"]["structure"]["about_heading"]
