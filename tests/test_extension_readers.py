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
    assert p["health"] == []


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
    assert p["health"] and p["health"][0]["problem"] == "Can't read this posting"
