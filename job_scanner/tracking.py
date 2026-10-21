"""After you apply: follow-ups that are due, how your applications turned out by fit score, and the week in review.

The results table is a record of what happened, not a model: it shows how often each score band led to an
interview, so you can see whether the scores mean anything for you. It doesn't change the scores."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import jobs

BANDS = ((80, "80+"), (70, "70-79"), (55, "55-69"), (40, "40-54"), (0, "Under 40"))
OPEN = ("saved", "applied", "interviewing")
ENOUGH = 10  # applications before the results say anything


def _reached(rec: dict, *statuses) -> bool:
    return rec.get("status") in statuses or any(h.get("status") in statuses for h in rec.get("history") or [])


def applied(rec: dict) -> bool:
    return bool(rec.get("applied_at")) or _reached(rec, "applied", "interviewing", "offer")


def band(score: int) -> str:
    return next(label for floor, label in BANDS if score >= floor)


def due(recs, today: date | None = None) -> list:
    """Open applications whose follow-up date has come, oldest first. An application with no follow-up date counts
    once it's been waiting `follow_up_days`."""
    today = today or datetime.now(timezone.utc).date()
    wait = timedelta(days=jobs.follow_up_days())
    out = []
    for r in recs:
        if r.get("status") not in OPEN:
            continue
        when = r.get("follow_up")
        if not when and r.get("status") == "applied" and r.get("applied_at"):
            when = (date.fromisoformat(r["applied_at"]) + wait).isoformat()
        if when and when <= today.isoformat():
            out.append((when, r))
    return [r for _, r in sorted(out, key=lambda x: x[0])]


def days_waiting(rec: dict, today: date | None = None):
    if not rec.get("applied_at"):
        return None
    return ((today or datetime.now(timezone.utc).date()) - date.fromisoformat(rec["applied_at"])).days


def outcomes(recs) -> dict:
    """Applications, interviews and offers per fit-score band, by the score each job had when you applied."""
    rows = {label: {"band": label, "applied": 0, "interviews": 0, "offers": 0, "rejected": 0} for _, label in BANDS}
    for r in recs:
        if not applied(r):
            continue
        row = rows[band(int(r.get("applied_score", jobs.best(r)["score"])))]
        row["applied"] += 1
        row["interviews"] += _reached(r, "interviewing", "offer")
        row["offers"] += _reached(r, "offer")
        row["rejected"] += r.get("status") == "rejected"
    table = [rows[label] for _, label in BANDS]
    total, interviews = sum(x["applied"] for x in table), sum(x["interviews"] for x in table)
    if total < ENOUGH:
        note = f"After {ENOUGH - total} more applications this shows which scores lead to interviews for you."
    elif not interviews:
        note = f"No interviews yet from {total} applications. That's common; the scores can't be checked against results yet."
    else:
        covered, floor = 0, None
        for (f, _), row in zip(BANDS, table):
            covered += row["interviews"]
            if covered >= 0.8 * interviews:
                floor = f
                break
        note = (f"{covered} of your {interviews} interviews came from jobs scored {floor} or more."
                if floor else f"{interviews} interviews from {total} applications.")
    return {"bands": table, "applied": total, "interviews": interviews, "note": note}


def digest(ledger, usage: dict, now: datetime | None = None) -> dict:
    """The last seven days: new jobs, the best ones you haven't acted on, what you sent, what moved, what's due."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=7)).isoformat(timespec="seconds")
    recs = list(ledger.jobs.values())
    events = [(h["at"], h["status"], r) for r in recs for h in r.get("history") or [] if h.get("at", "") >= since]
    top = [r for r in ledger.listing({"status": "untracked"}) if (r.get("last_seen") or "") >= since and not r.get("closed")]

    def brief(r):
        b = jobs.best(r)
        return {"key": r["key"], "title": r.get("title"), "company": r.get("company"), "score": b["score"],
                "verdict": b["verdict"], "by": b["by"], "source_name": jobs.SOURCES.get(r["source"], r["source"])}
    return {
        "since": since[:10],
        "new_jobs": sum(1 for r in recs if (r.get("first_seen") or "") >= since),
        "read_by_claude": sum(1 for r in recs if ((r.get("ai") or {}).get("at") or "") >= since),
        "best_unapplied": [brief(r) for r in top if jobs.best(r)["verdict"] != "Skip"][:8],
        "applied": [brief(r) for at, st, r in sorted(events, key=lambda e: e[0]) if st == "applied"],
        "moved": [{**brief(r), "status": st} for at, st, r in sorted(events, key=lambda e: e[0])
                  if st in ("interviewing", "offer", "rejected")],
        "due": [{**brief(r), "follow_up": r.get("follow_up"), "days_waiting": days_waiting(r)} for r in due(recs, now.date())],
        "usage": usage,
    }
