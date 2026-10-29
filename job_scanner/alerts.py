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
DEFAULTS = {"phone_topic": "", "phone_server": "", "phone_min": 70, "brief_hour": 7, "app_url": ""}
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
    if not (fresh or good or due or interviews):
        return None

    def line(r):
        b = best(r)
        return f"{b['verdict']} {b['score']} · {r.get('title') or '?'}" + (f" at {r['company']}" if r.get("company") else "")

    parts = []
    for r in interviews:
        when = "today" if r["interview_at"] == soon[0] else "tomorrow"
        parts.append(f"Interview {when}: {r.get('title') or '?'}" + (f" at {r['company']}" if r.get("company") else ""))
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
    if fresh:
        bits.append(f"{len(fresh)} fresh")
    if good:
        bits.append(f"{len(good)} new to apply for")
    if due:
        bits.append(f"{len(due)} to do")
    if interviews:
        bits.append(f"{len(interviews)} interview{'s' if len(interviews) > 1 else ''}")
    return "Morning: " + ", ".join(bits), "\n\n".join(parts)


def state() -> dict:
    return store.read_json(STATE, {"brief_date": "", "brief_at": "", "errors": 0, "last_error": ""})


def save_state(st: dict) -> None:
    store.write_json(STATE, st)
