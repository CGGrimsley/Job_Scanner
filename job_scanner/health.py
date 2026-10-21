"""Whether the extension can still read each site. Job sites change their pages often; when the extension finds a
posting or a page of search results it can't read, it reports it here so the app can say so instead of failing
silently. Kept in site_health.json: {source: {"posting"|"cards": {"ok", "at", "path"}}}."""

from __future__ import annotations

import re
import threading

from . import jobs, store

FILE = "site_health.json"
WHAT = ("posting", "cards")
_lock = threading.Lock()


def load() -> dict:
    return store.read_json(FILE, {})


def report(raw: dict) -> dict:
    source, what = str(raw.get("source") or ""), str(raw.get("what") or "")
    if source not in jobs.SOURCES or what not in WHAT:
        raise ValueError("Unknown site or check.")
    path = re.sub(r"[^\w/.:-]", "", str(raw.get("path") or ""))[:200]
    with _lock:
        data = load()
        data.setdefault(source, {})[what] = {"ok": bool(raw.get("ok")), "at": jobs.now_iso(), "path": path}
        store.write_json(FILE, data)
        return data


def problems(data: dict | None = None) -> list:
    """[(source, what, entry)] for every check whose latest report failed."""
    data = load() if data is None else data
    return [(s, w, e) for s, checks in data.items() for w, e in checks.items() if not e.get("ok")]
