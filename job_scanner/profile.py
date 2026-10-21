"""The person's profile: what they're looking for, their résumé and their About Me.

All of it is entered in the app (or imported from a résumé file) and kept in the data folder as profile.json.
The rules scorer uses the preferences; Claude gets all of it as context.
"""

from __future__ import annotations

import hashlib
import json

from . import store

REMOTE_CHOICES = ("remote", "hybrid", "onsite")
SENIORITY_CHOICES = ("intern", "entry", "mid", "senior", "lead", "manager", "director", "executive")
JOB_TYPE_CHOICES = ("full-time", "part-time", "contract", "temporary", "internship")

DEFAULT = {
    "name": "",
    "about_me": "",          # free text: who they are, what they want next, what matters to them
    "resume": "",            # plain text of the résumé
    "target_titles": [],     # e.g. ["data analyst", "business analyst"]
    "skills": [],            # what they can do; matched against postings
    "avoid_keywords": [],    # words that rule a posting out (e.g. "commission only", "door to door")
    "dealbreakers": "",      # free text for Claude (e.g. "no night shifts, no more than 25% travel")
    "locations": [],         # cities or regions they'd work in, e.g. ["Raleigh, NC", "Durham, NC"]
    "remote": ["remote", "hybrid", "onsite"],
    "seniority": [],         # which levels to look at; empty = any
    "job_types": ["full-time"],
    "years_experience": None,
    "min_salary": None,      # yearly; hourly pay is converted at 2,080 hours
    "max_age_days": 30,      # postings older than this lose points
}


def _list(v, n=60) -> list:
    if isinstance(v, str):
        v = [x for x in v.replace("\n", ",").split(",")]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        x = str(x).strip()
        if x and x.lower() not in {o.lower() for o in out}:
            out.append(x[:120])
    return out[:n]


def _num(v):
    if v in (None, ""):
        return None
    try:
        n = float(str(v).replace(",", "").replace("$", ""))
    except ValueError:
        return None
    return int(n) if n == int(n) else n


def clean(raw: dict) -> dict:
    """A profile from whatever the page sent: unknown keys dropped, every field the right type."""
    p = dict(DEFAULT)
    raw = raw if isinstance(raw, dict) else {}
    p["name"] = str(raw.get("name") or "").strip()[:120]
    p["about_me"] = str(raw.get("about_me") or "").strip()[:8000]
    p["resume"] = str(raw.get("resume") or "").strip()[:40000]
    p["dealbreakers"] = str(raw.get("dealbreakers") or "").strip()[:2000]
    for k in ("target_titles", "skills", "avoid_keywords", "locations"):
        p[k] = _list(raw.get(k, DEFAULT[k]))
    p["remote"] = [x for x in _list(raw.get("remote", DEFAULT["remote"])) if x in REMOTE_CHOICES] or list(REMOTE_CHOICES)
    p["seniority"] = [x for x in _list(raw.get("seniority", [])) if x in SENIORITY_CHOICES]
    p["job_types"] = [x for x in _list(raw.get("job_types", DEFAULT["job_types"])) if x in JOB_TYPE_CHOICES]
    p["years_experience"] = _num(raw.get("years_experience"))
    p["min_salary"] = _num(raw.get("min_salary"))
    age = _num(raw.get("max_age_days"))
    p["max_age_days"] = int(age) if age else DEFAULT["max_age_days"]
    return p


def load() -> dict:
    return clean(store.read_json("profile.json", {}))


def save(raw: dict) -> dict:
    p = clean(raw)
    store.write_json("profile.json", p)
    return p


def is_empty(p: dict) -> bool:
    return not (p.get("target_titles") or p.get("skills") or p.get("resume") or p.get("about_me"))


def fingerprint(p: dict) -> str:
    """Changes whenever anything Claude sees changes, so an old analysis can be marked out of date."""
    return hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]


def for_prompt(p: dict) -> str:
    """The profile as Claude reads it."""
    lines = []
    if p["name"]:
        lines.append(f"Name: {p['name']}")
    if p["target_titles"]:
        lines.append("Roles they want: " + "; ".join(p["target_titles"]))
    if p["seniority"]:
        lines.append("Levels: " + ", ".join(p["seniority"]))
    if p["years_experience"] is not None:
        lines.append(f"Years of experience: {p['years_experience']}")
    if p["skills"]:
        lines.append("Skills: " + "; ".join(p["skills"]))
    if p["locations"]:
        lines.append("Locations: " + "; ".join(p["locations"]))
    lines.append("Work arrangements they accept: " + ", ".join(p["remote"]))
    if p["job_types"]:
        lines.append("Job types: " + ", ".join(p["job_types"]))
    if p["min_salary"]:
        lines.append(f"Minimum pay: ${p['min_salary']:,} a year")
    if p["avoid_keywords"]:
        lines.append("Avoid postings mentioning: " + "; ".join(p["avoid_keywords"]))
    if p["dealbreakers"]:
        lines.append("Dealbreakers: " + p["dealbreakers"])
    out = "\n".join(lines)
    if p["about_me"]:
        out += "\n\n## About me (in their words)\n" + p["about_me"]
    if p["resume"]:
        out += "\n\n## Résumé\n" + p["resume"]
    return out
