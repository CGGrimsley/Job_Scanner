"""Phone alerts and the morning brief, through ntfy (https://ntfy.sh: free, no account, an app for iPhone and
Android). The person picks a hard-to-guess topic name, subscribes to it in the ntfy app, and pastes it on Setup.

What reaches the phone:
- a job the app found by itself (Watching) once Claude has read it and says Apply at `phone_min` or more. A job
  posted in the last day gets `FRESH_EASE` points of slack, since applying early matters most. When Claude
  couldn't read it (off, or the day's limit is used up), only a quick score of `RULES_MIN` or more is sent, and
  the alert says it's the quick score.
- once a day at `brief_hour` (local time; set TZ in Docker), the morning brief: fresh and best new matches,
  to-dos due today and interviews today or tomorrow.

Each job is sent once (rec["pushed"]). Nothing personal beyond job titles, employers and the person's own to-dos
is sent; the topic name is the only thing that keeps it private, so it should be long and random.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from . import scoring, store

DEFAULT_SERVER = os.environ.get("JOB_SCANNER_NTFY_SERVER", "https://ntfy.sh")
DEFAULTS = {"phone_topic": "", "phone_server": "", "phone_min": 70, "brief_hour": 7, "app_url": "",
            "drafts_per_night": 2, "drafts_hour": 4, "evening_hour": 19}
DRAFT_WITHIN_DAYS = 3  # overnight drafts are for jobs found in the last few days
FRESH_EASE = 10   # a job posted in the last day reaches the phone this many points lower
RULES_MIN = 80    # without Claude's read, only a quick score this high is sent
PER_RUN = 5       # alerts per check, at most: a new board can add dozens of jobs at once
STATE = "alerts.json"


class AlertError(RuntimeError):
    pass


def valid_topic(topic: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{6,64}", topic or ""))


def config() -> dict:
    s = store.settings()
    out = {k: s.get(k, v) for k, v in DEFAULTS.items()}
    out["phone_server"] = (out["phone_server"] or DEFAULT_SERVER).rstrip("/")
    out["app_url"] = (out["app_url"] or os.environ.get("JOB_SCANNER_PUBLIC_URL", "")).rstrip("/")
    return out


def on(cfg: dict) -> bool:
    return valid_topic(cfg.get("phone_topic"))


def _ascii(s: str) -> str:
    """HTTP headers are latin-1: keep titles and action labels plain (the body carries full UTF-8)."""
    s = s.replace("·", "-").replace("–", "-").replace("—", "-").replace("’", "'")
    return s.encode("ascii", "ignore").decode()


def send(cfg: dict, title: str, body: str, url: str = "", actions: list | None = None,
         tags: str = "briefcase", priority: str = "default") -> None:
    if not on(cfg):
        raise AlertError("Set an ntfy topic on Setup first (6 to 64 letters, digits, - or _).")
    headers = {"Title": _ascii(title)[:200], "Tags": tags, "Priority": priority}
    if url:
        headers["Click"] = url
    if actions:
        headers["Actions"] = "; ".join(f"view, {_ascii(label).replace(',', ' ')}, {link}" for label, link in actions[:3])
    req = urllib.request.Request(f"{cfg['phone_server']}/{cfg['phone_topic']}", data=body.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise AlertError(f"ntfy didn't take the alert: {getattr(e, 'reason', e)}") from None


def app_link(cfg: dict, key: str = "") -> str:
    if not cfg.get("app_url"):
        return ""
    return cfg["app_url"] + "/" + (f"#job/{urllib.request.quote(key, safe='')}" if key else "")


# ---------- jobs ----------
def is_fresh(rec: dict) -> bool:
    from .jobs import fresh

    return fresh(rec)


def worth_pushing(rec: dict, floor: int) -> bool:
    """A job the person hasn't acted on, rated Apply by Claude at `floor` or more (less FRESH_EASE when it's fresh),
    or, unread, a quick score of RULES_MIN or more."""
    from .jobs import best

    if rec.get("pushed") or rec.get("status") or rec.get("closed") or (rec.get("rules") or {}).get("scam"):
        return False
    b = best(rec)
    if b["verdict"] != scoring.APPLY:
        return False
    need = floor - (FRESH_EASE if is_fresh(rec) else 0)
    if b["by"] == "rules":
        need = max(need, RULES_MIN)
    return b["score"] >= need


def job_alert(rec: dict, cfg: dict) -> tuple:
    """(title, body, click url, actions) for one job."""
    from .jobs import best

    b = best(rec)
    r = rec.get("rules") or {}
    head = f"{b['verdict']} {b['score']} - {rec.get('title') or 'A job'}"
    if rec.get("company"):
        head += f" at {rec['company']}"
    bits = [x for x in (rec.get("location") or "", f"up to ${r['pay_max']:,}" if r.get("pay_max") else "",
                        "posted in the last day" if is_fresh(rec) else "") if x]
    lines = [" · ".join(bits)] if bits else []
    ai = rec.get("ai") or {}
    if b["by"] == "ai":
        lines.append(ai.get("interview_odds") or ai.get("summary") or "")
    else:
        lines.append("Quick score only: Claude hasn't read it yet.")
    if rec.get("found_by"):
        lines.append(f"Found by watching {rec['found_by']}")
    url = rec.get("url") or app_link(cfg, rec["key"])
    actions = [("Open posting", rec["url"])] if rec.get("url") else []
    if app_link(cfg):
        actions.append(("In Job Scanner", app_link(cfg, rec["key"])))
    return head, "\n".join(x for x in lines if x), url, actions


def push_jobs(recs: list, cfg: dict) -> list:
    """Send the jobs worth it, best first (fresh ones first among equals). Returns the keys sent."""
    from .jobs import best

    if not on(cfg):
        return []
    floor = int(cfg.get("phone_min") or DEFAULTS["phone_min"])
    todo = sorted((r for r in recs if worth_pushing(r, floor)), key=lambda r: (-best(r)["score"], not is_fresh(r)))
    sent = []
    for rec in todo[:PER_RUN]:
        title, body, url, actions = job_alert(rec, cfg)
        send(cfg, title, body, url, actions, tags="star" if is_fresh(rec) else "briefcase",
             priority="high" if best(rec)["by"] == "ai" else "default")
        sent.append(rec["key"])
    return sent


# ---------- overnight drafts ----------
def at_hour(now: datetime, hour, last: str) -> bool:
    """Once a day, at or after `hour` local time (-1 or None turns it off)."""
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return False
    return 0 <= hour <= 23 and now.hour >= hour and last != now.date().isoformat()


def draft_candidates(recs: list, n: int, now: datetime) -> list:
    """The new jobs Claude rated Apply that are worth an application drafted overnight: not acted on, a full
    posting, found in the last few days, no application drafted yet. Fresh first, then best."""
    from .jobs import best

    def recent(r):
        try:
            return now - datetime.fromisoformat(r.get("first_seen") or "") <= timedelta(days=DRAFT_WITHIN_DAYS)
        except (TypeError, ValueError):
            return False

    pool = [r for r in recs if not r.get("status") and not r.get("closed") and r.get("description") and recent(r)
            and not r.get("packet") and not r.get("overnight") and not (r.get("rules") or {}).get("scam")
            and best(r)["by"] == "ai" and best(r)["verdict"] == scoring.APPLY]
    return sorted(pool, key=lambda r: (not is_fresh(r), -best(r)["score"]))[:max(0, n)]


# ---------- interviews ----------
def interviews_on(recs: list, day: date) -> list:
    return [r for r in recs if r.get("status") == "interviewing" and r.get("interview_at") == day.isoformat()]


def reminder(rec: dict, cfg: dict) -> tuple:
    """(title, body) for the evening before an interview."""
    who = (rec.get("title") or "your interview") + (f" at {rec['company']}" if rec.get("company") else "")
    prep = rec.get("interview") or {}
    lines = ["Your prep is ready in Job Scanner: likely questions, what in your résumé answers them, and questions to ask."
             if prep else "Open the job in Job Scanner for interview prep."]
    for q in (prep.get("ask_them") or [])[:2]:
        lines.append(f"Ask them: {q.get('question') if isinstance(q, dict) else q}")
    return f"Interview tomorrow: {who}", "\n".join(lines)


def thanks_due(recs: list, today: date) -> list:
    """Interviews that have happened (today or earlier, within a week) with no thank-you drafted since."""
    out = []
    for r in recs:
        when = r.get("interview_at") or ""
        if r.get("status") != "interviewing" or not when or when > today.isoformat():
            continue
        try:
            if (today - date.fromisoformat(when)).days > 7:
                continue
        except ValueError:
            continue
        if ((r.get("draft_thank_you") or {}).get("at") or "")[:10] < when:
            out.append(r)
    return out


# ---------- the morning brief ----------
def brief_due(now: datetime, cfg: dict, last: str) -> bool:
    """Once a day, at or after brief_hour local time (-1 turns it off)."""
    hour = int(cfg.get("brief_hour") if cfg.get("brief_hour") is not None else -1)
    return on(cfg) and 0 <= hour <= 23 and now.hour >= hour and last != now.date().isoformat()


def brief(recs: list, todo: list, today: date, since: datetime) -> tuple | None:
    """(title, body) of the morning brief, or None when there's nothing to say. `todo` is advice.todo(...);
    `since` is when the last brief went (new matches are counted from then)."""
    from .jobs import best

    def new(r):
        try:
            return datetime.fromisoformat(r.get("first_seen") or "") >= since
        except ValueError:
            return False

    open_ = [r for r in recs if not r.get("status") and not r.get("closed") and not (r.get("rules") or {}).get("scam")]
    fresh = [r for r in open_ if is_fresh(r) and best(r)["verdict"] != scoring.SKIP]
    good = sorted((r for r in open_ if new(r) and best(r)["verdict"] == scoring.APPLY), key=lambda r: -best(r)["score"])
    due = [n for n in todo if n.get("urgency") == "now"]
    soon = (today.isoformat(), (today + timedelta(days=1)).isoformat())
    interviews = [r for r in recs if r.get("status") == "interviewing" and (r.get("interview_at") or "") in soon]
    ready = [r for r in open_ if new_doc(r.get("overnight"), since)]
    thanks = [r for r in recs if new_doc(r.get("draft_thank_you"), since)]
    if not (fresh or good or due or interviews or ready or thanks):
        return None

    def line(r):
        b = best(r)
        return f"{b['verdict']} {b['score']} · {r.get('title') or '?'}" + (f" at {r['company']}" if r.get("company") else "")

    parts = []
    for r in interviews:
        when = "today" if r["interview_at"] == soon[0] else "tomorrow"
        parts.append(f"Interview {when}: {r.get('title') or '?'}" + (f" at {r['company']}" if r.get("company") else ""))
    if ready:
        parts.append("Applications drafted overnight, ready to review:\n" + "\n".join("- " + line(r) for r in ready[:4]))
    if thanks:
        parts.append("Thank-you notes drafted: " + "; ".join((r.get("company") or r.get("title") or "?") for r in thanks[:3]))
    if due:
        parts.append("To do today:\n" + "\n".join(f"- {n['title']}: {n.get('title_job') or '?'}" for n in due[:5]))
    shown = set()
    if fresh:
        top = sorted(fresh, key=lambda r: -best(r)["score"])[:4]
        shown.update(r["key"] for r in top)
        parts.append("Posted in the last day:\n" + "\n".join("- " + line(r) for r in top))
    rest = [r for r in good if r["key"] not in shown][:4]
    if rest:
        parts.append(f"New matches ({len(good)}):\n" + "\n".join("- " + line(r) for r in rest))
    bits = []
    if ready:
        bits.append(f"{len(ready)} ready to send")
    if fresh:
        bits.append(f"{len(fresh)} fresh")
    if good:
        bits.append(f"{len(good)} new to apply for")
    if due:
        bits.append(f"{len(due)} to do")
    if interviews:
        bits.append(f"{len(interviews)} interview{'s' if len(interviews) > 1 else ''}")
    return "Morning: " + ", ".join(bits), "\n\n".join(parts)


def new_doc(doc, since: datetime) -> bool:
    try:
        return bool(doc) and datetime.fromisoformat(doc.get("at") or "") >= since
    except (TypeError, ValueError, AttributeError):
        return False


def state() -> dict:
    return store.read_json(STATE, {"brief_date": "", "brief_at": "", "errors": 0, "last_error": ""})


def save_state(st: dict) -> None:
    store.write_json(STATE, st)
