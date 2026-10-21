import json
import subprocess
import threading
import time

import pytest

from job_scanner import ai, companies, health, startup, store


@pytest.fixture(autouse=True)
def no_limit(monkeypatch):
    monkeypatch.setattr(ai, "_limited", {"until": None, "text": ""})
    monkeypatch.setattr(ai, "RETRY_WAIT", 0)


def cli(monkeypatch, answers):
    """Fake Claude Code: each call pops the next (payload, exit code)."""
    monkeypatch.setenv("JOB_SCANNER_AI", "cli")
    monkeypatch.setattr(ai.shutil, "which", lambda name: "/usr/bin/claude")
    calls = []

    def run(cmd, **kw):
        calls.append({"cmd": cmd, "system": open(kw["cwd"] + "/" + ai.SYSTEM_FILE, encoding="utf-8").read()})
        payload, code = answers.pop(0)
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(ai.subprocess, "run", run)
    return calls


def test_classify():
    assert ai.classify("Claude AI usage limit reached|1729526400")[0] == "limit"
    assert ai.classify("You've hit your limit · resets 3pm (America/New_York)") == ("limit", "3pm (America/New_York)")
    assert ai.classify("API Error: 529 Overloaded")[0] == "transient"
    assert ai.classify("Invalid API key · Please run /login")[0] == "auth"
    assert ai.classify("something odd")[0] == "other"


def test_transient_error_is_retried_once(monkeypatch):
    calls = cli(monkeypatch, [({"is_error": True, "result": "API Error: 529 Overloaded"}, 1),
                              ({"structured_output": {"ok": True}}, 0)])
    assert ai.ask_json("SYS", "hi", {"type": "object"}) == {"ok": True}
    assert len(calls) == 2
    assert "--system-prompt-file" in calls[0]["cmd"] and calls[0]["system"] == "SYS"


def test_plan_limit_pauses_automatic_reads(monkeypatch):
    calls = cli(monkeypatch, [({"is_error": True, "result": "Claude AI usage limit reached · resets 3pm"}, 1)])
    with pytest.raises(ai.AIError) as e:
        ai.ask_json("s", "p", {"type": "object"})
    assert e.value.kind == "limit" and len(calls) == 1  # never retried
    assert "resets at 3pm" in ai.limited()
    with pytest.raises(ai.AIError, match="usage limit"):
        ai.ask_json("s", "p", {"type": "object"})  # no new call while the limit holds
    assert len(calls) == 1


def test_gate_puts_asked_for_first_and_newest_automatic_next():
    gate = ai.Gate(1)
    gate.enter(0)  # something running
    order = []

    def wait(name, prio, cancelled=None):
        try:
            gate.enter(prio, cancelled)
        except ai.AIError:
            order.append(name + " skipped")
            return
        order.append(name)
        gate.leave()

    threads = []
    for name, prio, cancel in (("auto-old", 1, None), ("auto-closed", 1, lambda: True), ("auto-new", 1, None), ("asked", 0, None)):
        t = threading.Thread(target=wait, args=(name, prio, cancel))
        t.start()
        threads.append(t)
        time.sleep(0.05)
    gate.leave()
    for t in threads:
        t.join(5)
    assert order == ["auto-closed skipped", "asked", "auto-new", "auto-old"]


def test_model_per_task(monkeypatch):
    assert ai.model_for("company") == "haiku"
    store.save_settings({"model_main": "opus", "model_light": "", "model_auto": "light"})
    assert ai.model_for("analyze") == "opus"
    assert ai.model_for("company") == "opus"  # "same as above"
    store.save_settings({"model_light": "sonnet"})
    assert ai.model_for("analyze", auto=True) == "sonnet"


def test_company_read_is_honest_when_unknown(monkeypatch):
    cli(monkeypatch, [({"structured_output": {"known": False, "summary": "A big bank, probably", "industry": "Banking",
                                              "size": "large (1,000-10,000)", "notes": ["x"], "check": ["Glassdoor"]}}, 0)])
    out = ai.company_read({"title": "Analyst", "company": "Acme Staffing"})
    assert out["summary"] == "" and out["notes"] == [] and out["check"] == ["Glassdoor"]
    saved = companies.put("Acme Staffing, Inc.", out)
    assert companies.get("ACME staffing") == saved and companies.fresh(saved)
    assert companies.context(saved) == ""  # nothing unknown goes into the analysis
    assert "general knowledge" in companies.context({"known": True, "summary": "Makes widgets.", "notes": []})


def test_site_health_reports():
    health.report({"source": "linkedin", "what": "cards", "ok": False, "path": "/jobs/search<script>"})
    assert health.problems()[0][:2] == ("linkedin", "cards")
    assert "<" not in health.load()["linkedin"]["cards"]["path"]
    health.report({"source": "linkedin", "what": "cards", "ok": True})
    assert health.problems() == []
    with pytest.raises(ValueError):
        health.report({"source": "evil", "what": "cards"})


def test_startup_script_quotes_paths():
    vbs = startup.script(r'C:\Users\a "b"\job_scanner', r"C:\Python\pythonw.exe")
    assert 'sh.CurrentDirectory = "C:\\Users\\a ""b""\\job_scanner"' in vbs
    assert '"""C:\\Python\\pythonw.exe"" -m job_scanner serve", 0, False' in vbs
