"""What an employer's own postings say about it, read once by Claude and reused for all of its jobs. Kept in
companies.json, keyed by the employer's normalised name."""

from __future__ import annotations

import threading

from . import groups, jobs, store

FILE = "companies.json"
_lock = threading.Lock()


def key(name: str | None) -> str:
    return groups.company_key(name)


def load() -> dict:
    return store.read_json(FILE, {})


def get(name: str | None, data: dict | None = None) -> dict | None:
    k = key(name)
    return (load() if data is None else data).get(k) if k else None


def save(name: str, read: dict, postings: int) -> dict:
    with _lock:
        data = store.read_json(FILE, {})
        data[key(name)] = entry = {"name": name, "read": read, "postings": postings, "at": jobs.now_iso()}
        store.write_json(FILE, data)
        return entry


def postings_of(ledger, name: str, limit: int = 5) -> list:
    """The employer's captured postings with a description, newest first."""
    k = key(name)
    recs = [r for r in ledger.jobs.values() if r.get("description") and key(r.get("company")) == k]
    return sorted(recs, key=lambda r: r.get("last_seen") or "", reverse=True)[:limit]
