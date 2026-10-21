"""One read per employer: what Claude knows about a company in general, kept in companies.json and reused for every
posting from that company. Claude can't browse here, so a read is general knowledge that may be out of date, and an
employer Claude doesn't recognise is stored as unknown rather than guessed at.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from . import store
from .signals import norm_company

FILE = "companies.json"
STALE_DAYS = 180
_lock = threading.Lock()


def key(name: str) -> str:
    return norm_company(name or "")


def get(name: str) -> dict | None:
    k = key(name)
    return store.read_json(FILE, {}).get(k) if k else None


def fresh(read: dict | None, now: datetime | None = None) -> bool:
    if not read:
        return False
    try:
        at = datetime.fromisoformat(read["at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (now or datetime.now(timezone.utc)) - at < timedelta(days=STALE_DAYS)


def put(name: str, read: dict) -> dict:
    k = key(name)
    if not k:
        return read
    read = {**read, "name": name, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _lock:
        data = store.read_json(FILE, {})
        data[k] = read
        store.write_json(FILE, data)
    return read


def context(read: dict | None) -> str:
    """A line for the analysis prompt, or "" when Claude didn't recognise the employer."""
    if not read or not read.get("known"):
        return ""
    bits = [read.get("summary") or ""]
    if read.get("notes"):
        bits.append("Worth knowing: " + "; ".join(read["notes"]))
    return "- About the employer (general knowledge, may be out of date): " + " ".join(b for b in bits if b)
