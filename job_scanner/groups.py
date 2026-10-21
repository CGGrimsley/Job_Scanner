"""The same job seen more than once: on LinkedIn, on Indeed and on the employer's own site, or listed again under a
new id.

Copies are matched by employer and title, normalised. When copies name different cities they're split by city, so
one employer's "Data Analyst" in Raleigh and in Austin stay separate jobs. Each copy keeps its own record; the app
lists the job once and says where else it's posted.

A job that keeps coming back is flagged as reposted: listed again on the same site a week or more after it was
first seen, its posting date moved forward, or the site itself says "Reposted". That can mean a ghost job or a role
that's hard to keep filled, so it's shown as a caution, not a verdict."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from .scoring import words

REPOST_GAP_DAYS = 7
_CO_SUFFIX = re.compile(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|lp|llp|holdings|the)\b")
_TITLE_TAIL = re.compile(r"\s+[-–|/]\s+(remote|hybrid|on-?site|in[- ]office|work from home|wfh|[a-z .]+,\s*[a-z]{2})\s*$")


def company_key(name: str | None) -> str:
    s = re.sub(r"[^\w\s]", " ", (name or "").lower().replace("&", " and "))
    return " ".join(_CO_SUFFIX.sub(" ", s).split())


def title_key(title: str | None) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (title or "").lower())
    t = _TITLE_TAIL.sub("", t.strip())
    return " ".join(words(t))


def city_of(location: str | None) -> str:
    loc = (location or "").lower()
    if not loc:
        return ""
    if re.search(r"\bremote\b", loc) and not re.search(r"\bhybrid\b", loc):
        return "remote"
    return " ".join(re.sub(r"\(.*?\)|\d+", " ", loc.split(",")[0]).split())


def build(jobs: dict) -> dict:
    """{job key: group id} for every job whose employer and title are known."""
    buckets = defaultdict(list)
    for key, r in jobs.items():
        c, t = company_key(r.get("company")), title_key(r.get("title"))
        if c and t:
            buckets[f"{c}|{t}"].append(key)
    out = {}
    for b, keys in buckets.items():
        cities = {city_of(jobs[k].get("location")) for k in keys} - {""}
        for k in keys:
            if len(cities) <= 1:
                out[k] = b
            elif city_of(jobs[k].get("location")):
                out[k] = f"{b}|{city_of(jobs[k].get('location'))}"
    return out


def _days(a: str, b: str) -> int:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
    except ValueError:
        return 0


def reposts(recs: list) -> dict | None:
    """{'count', 'since'} for one job's copies, or None if it hasn't been reposted."""
    count = 0
    by_source = defaultdict(list)
    for r in recs:
        by_source[r["source"]].append(r.get("first_seen") or "")
        count += int(r.get("reposts") or 0)
    for seen in by_source.values():
        seen.sort()
        count += sum(1 for a, b in zip(seen, seen[1:]) if a and b and _days(a, b) >= REPOST_GAP_DAYS)
    if not count and any(re.search(r"\brepost", r.get("posted_text") or "", re.I) for r in recs):
        count = 1
    if not count:
        return None
    since = min((r.get("first_seen") or "" for r in recs), default="")[:10]
    return {"count": count, "since": since}


def annotate(rec: dict, info: dict | None) -> None:
    """Keep the record's repost flag and its caution in step with what its copies show."""
    rules = rec.get("rules")
    cautions = [c for c in (rules or {}).get("cautions", []) if not c.startswith("Reposted")]
    if info:
        rec["repost"] = info
        times = "once" if info["count"] == 1 else f"{info['count']} times"
        cautions.append(f"Reposted {times} (first seen {info['since']}): can mean a ghost job or a hard-to-fill role")
    else:
        rec.pop("repost", None)
    if rules is not None:
        rules["cautions"] = cautions
