"""What all your jobs say together: how Claude's verdicts have held up against what actually happened, the skills
your target jobs keep asking for that your résumés don't show, and what those jobs pay.

Everything here is counted from your own ledger. Small numbers are labelled as small: a rate from four applications
says very little, and the page says so rather than dressing it up.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from statistics import median

from . import scoring

APPLIED = ("applied", "interviewing", "offer", "rejected", "withdrawn")
NO_REPLY_DAYS = 30
MIN_SAMPLE = 5


def _days_since(iso: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return None


def outcome(rec: dict, today: date) -> str:
    """interview, rejected, no_reply, waiting or withdrawn, for a job you applied to."""
    seen = {h.get("status") for h in rec.get("history") or []} | {rec.get("status")}
    if seen & {"interviewing", "offer"}:
        return "interview"
    if rec.get("status") == "rejected":
        return "rejected"
    if rec.get("status") == "withdrawn":
        return "withdrawn"
    days = _days_since(rec.get("applied_at") or "", today)
    return "no_reply" if days is not None and days >= NO_REPLY_DAYS else "waiting"


def accuracy(recs: list, today: date | None = None) -> dict:
    """How jobs did after you applied, grouped by the verdict they had when you applied."""
    from .jobs import best

    today = today or date.today()
    rows = {v: {"verdict": v, "applied": 0, "interview": 0, "rejected": 0, "no_reply": 0, "waiting": 0}
            for v in (scoring.APPLY, scoring.CONSIDER, scoring.SKIP)}
    by_claude = {"claude": [0, 0], "rules": [0, 0]}  # [decided, interviews]
    for r in recs:
        if r.get("status") not in APPLIED and not any(h.get("status") in APPLIED for h in r.get("history") or []):
            continue
        o = outcome(r, today)
        if o == "withdrawn":
            continue
        snap = r.get("applied_score") or best(r)
        row = rows.get(snap.get("verdict")) or rows[scoring.CONSIDER]
        row["applied"] += 1
        row[o] += 1
        if o != "waiting":
            b = by_claude["claude" if snap.get("by") == "ai" else "rules"]
            b[0] += 1
            b[1] += o == "interview"
    for row in rows.values():
        decided = row["applied"] - row["waiting"]
        row["decided"] = decided
        row["rate"] = round(100 * row["interview"] / decided) if decided else None
        row["enough"] = decided >= MIN_SAMPLE
    decided = sum(r["decided"] for r in rows.values())
    a, c, s = rows[scoring.APPLY], rows[scoring.CONSIDER], rows[scoring.SKIP]
    if decided < MIN_SAMPLE * 2:
        note = (f"{decided} application{'' if decided == 1 else 's'} with a result so far. That's too few to say whether the "
                "scores are right; this fills in as you mark jobs Applied, Interviewing or Rejected. An application "
                f"with no reply after {NO_REPLY_DAYS} days counts as no reply.")
    elif a["enough"] and c["enough"] and a["rate"] <= c["rate"]:
        note = (f"Jobs rated Apply have led to interviews {a['rate']}% of the time, no better than Consider ({c['rate']}%). "
                "The scores aren't separating your chances well yet: read Claude's gaps closely rather than trusting the number.")
    elif a["enough"] and s["enough"] and s["rate"] >= a["rate"]:
        note = (f"Jobs rated Skip have done as well as Apply ({s['rate']}% vs {a['rate']}%). The scores may be too harsh for "
                "you, or those were special cases (a referral, say).")
    elif a["enough"]:
        others = [x for x in (c, s) if x["enough"]]
        vs = ", ".join(f"{x['verdict']} {x['rate']}%" for x in others)
        note = (f"Jobs rated Apply have led to interviews {a['rate']}% of the time" + (f" ({vs})." if vs else ".") +
                " The verdicts are pointing the right way so far.")
    else:
        note = "Not enough results in each group yet to compare them."
    return {"rows": list(rows.values()), "decided": decided, "note": note,
            "by_claude": {k: {"decided": v[0], "interviews": v[1], "rate": round(100 * v[1] / v[0]) if v[0] else None}
                          for k, v in by_claude.items()}}


# ---------- skills your target jobs ask for ----------
def _has(term: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text) is not None


def _relevant(r: dict) -> bool:
    ai = r.get("ai") or {}
    return bool(ai) and r.get("status") != "dismissed" and (bool(r.get("status")) or ai.get("verdict") in ("Apply", "Consider"))


def skill_gaps(recs: list, profile: dict) -> dict:
    """Keywords Claude pulled from the jobs you'd consider that none of your résumés mention, and the gaps Claude
    raised, grouped and counted."""
    from .profile import all_resume_text

    resume = (all_resume_text(profile) + "\n" + (profile.get("about_me") or "")).lower()
    skills = {s.lower() for s in profile.get("skills") or []}
    jobs = [r for r in recs if _relevant(r)]
    words: dict = {}
    for r in jobs:
        for k in {str(k).strip() for k in (r["ai"].get("keywords") or []) if str(k).strip()}:
            if len(k) > 40 or _has(k, resume):
                continue
            e = words.setdefault(k.lower(), {"term": k, "jobs": 0, "on_skills_list": k.lower() in skills})
            e["jobs"] += 1
    missing = sorted(words.values(), key=lambda e: -e["jobs"])[:20]

    groups: list = []
    for r in jobs:
        for g in r["ai"].get("gaps") or []:
            if not isinstance(g, dict) or not g.get("requirement"):
                continue
            ws = set(scoring.words(g["requirement"])) - {"experience", "years", "knowledge", "ability", "strong", "proficiency"}
            if not ws:
                continue
            home = next((x for x in groups if len(ws & x["words"]) / len(ws | x["words"]) >= 0.5), None)
            if home is None:
                home = {"words": set(ws), "requirement": g["requirement"], "jobs": set(), "severity": {}}
                groups.append(home)
            home["jobs"].add(r["key"])
            sev = g.get("severity") or "minor"
            home["severity"][sev] = home["severity"].get(sev, 0) + 1
    gaps = sorted(({"requirement": x["requirement"], "jobs": len(x["jobs"]), "severity": x["severity"]} for x in groups),
                  key=lambda x: -x["jobs"])[:15]
    return {"jobs": len(jobs), "missing_keywords": [m for m in missing if m["jobs"] >= 2] or missing[:8], "gaps": gaps}


# ---------- pay ----------
def _mid(r: dict) -> float | None:
    x = r.get("rules") or {}
    lo, hi = x.get("pay_min"), x.get("pay_max")
    if lo is None and hi is None:
        return None
    return ((lo or hi) + (hi or lo)) / 2


def _quartiles(vals: list) -> dict:
    v = sorted(vals)
    q = lambda p: v[min(len(v) - 1, int(round(p * (len(v) - 1))))]  # noqa: E731
    return {"n": len(v), "low": round(q(0.25)), "median": round(median(v)), "high": round(q(0.75))}


def pay_report(recs: list, profile: dict) -> dict:
    """Typical pay, per target title, from postings you've seen that list it (yearly; hourly × 2,080)."""
    from .scoring import _place_match, _title_match

    places = profile.get("locations") or []
    out = []
    for title in (profile.get("target_titles") or [])[:10]:
        everywhere, near = [], []
        for r in recs:
            m = _mid(r)
            if m is None or _title_match(r.get("title") or "", [title]) < 0.99:
                continue
            everywhere.append(m)
            if places and (_place_match(r.get("location") or "", places) or (r.get("rules") or {}).get("remote") == "remote"):
                near.append(m)
        row = {"title": title, "everywhere": _quartiles(everywhere) if everywhere else {"n": 0}}
        if places:
            row["near"] = _quartiles(near) if near else {"n": 0}
        out.append(row)
    listed = sum(1 for r in recs if _mid(r) is not None)
    return {"titles": out, "listed": listed, "total": len(recs), "min_sample": MIN_SAMPLE}


def pay_position(rec: dict, recs: list) -> dict | None:
    """Where this job's pay sits among similar postings (titles sharing most words) you've seen."""
    mine = _mid(rec)
    if mine is None:
        return None
    from .scoring import _title_match

    others = [m for r in recs if r is not rec and r["key"] != rec["key"] and (m := _mid(r)) is not None
              and _title_match(r.get("title") or "", [rec.get("title") or ""]) >= 0.75]
    if len(others) < MIN_SAMPLE:
        return {"n": len(others), "enough": False}
    below = sum(1 for m in others if m < mine)
    return {"n": len(others), "enough": True, "percentile": round(100 * below / len(others)), **_quartiles(others)}


def weekly(recs: list, now: datetime, due: list | None = None, usage: dict | None = None) -> dict:
    """The last seven days: new strong matches you haven't acted on, what you sent, what moved forward or closed,
    follow-ups due (advice.todo items marked now) and how much Claude was used."""
    from .jobs import best, SOURCES

    def recent(iso, days=7):
        try:
            return (now - datetime.fromisoformat(iso)).days < days
        except (TypeError, ValueError):
            return False

    def brief(r):
        b = best(r)
        return {"key": r["key"], "title": r.get("title"), "company": r.get("company"), "score": b["score"],
                "verdict": b["verdict"], "by": b["by"], "source_name": SOURCES.get(r["source"], r["source"])}

    fresh = sorted((r for r in recs if recent(r.get("first_seen")) and not r.get("status") and not r.get("closed")
                    and best(r)["score"] >= 70), key=lambda r: -best(r)["score"])
    sent = [r for r in recs if r.get("applied_at") and _days_since(r["applied_at"], now.date()) is not None
            and _days_since(r["applied_at"], now.date()) < 7]
    moved = sorted(((h["at"], h["status"], r) for r in recs for h in r.get("history") or []
                    if h.get("status") in ("interviewing", "offer", "rejected", "withdrawn") and recent(h.get("at"))),
                   key=lambda e: e[0], reverse=True)
    return {"new_matches": len(fresh), "applied": len(sent),
            "new_jobs": sum(1 for r in recs if recent(r.get("first_seen"))),
            "read_by_claude": sum(1 for r in recs if recent((r.get("ai") or {}).get("at"))),
            "best_unapplied": [brief(r) for r in fresh[:5]],
            "sent": [brief(r) for r in sent],
            "moved": [{**brief(r), "status": st, "at": at[:10]} for at, st, r in moved],
            "due": [n for n in (due or []) if n.get("urgency") == "now"][:8],
            "usage": usage or {}}
