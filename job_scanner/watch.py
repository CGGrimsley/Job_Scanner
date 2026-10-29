"""Automatic sources, checked on a schedule while the app runs: employers' job boards, USAJobs and Adzuna searches,
and LinkedIn and Indeed alert emails (see feeds.py and mail.py for what each one is and isn't allowed to touch).

Only jobs worth a look are kept: those whose quick score reaches `min_score` and that are in one of the profile's
places (or remote, if they take remote work). Settings live in watch.json, results in watch_state.json, both in the
data folder. Keys and the mail password are stored there too, on this computer only, and never sent back to the
page once saved.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta, timezone

from . import feeds, jobs, mail, scoring, store

FILE, STATE = "watch.json", "watch_state.json"
DEFAULT = {
    "every_hours": 1, "min_score": 45, "boards": [],
    "searches": {"keywords": [], "where": "", "radius_miles": 25},
    "usajobs": {"enabled": False, "email": "", "key": ""},
    "adzuna": {"enabled": False, "app_id": "", "app_key": ""},
    "email": {"enabled": False, "host": "imap.gmail.com", "port": 993, "user": "", "password": "", "folder": "INBOX"},
    "nearby": None, "auto_boards": True,
}
AUTO_RETRY_HOURS = 24  # a failed or empty set-up is tried again after this long
SECRETS = (("usajobs", "key"), ("adzuna", "app_key"), ("email", "password"))
_lock = threading.Lock()
_running = threading.Lock()


def load() -> dict:
    cfg = copy.deepcopy(DEFAULT)
    saved = store.read_json(FILE, {})
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        elif k in cfg:
            cfg[k] = v
    return cfg


def public(cfg: dict) -> dict:
    """The settings for the page: secrets replaced by whether they're set."""
    out = copy.deepcopy(cfg)
    for section, key in SECRETS:
        out[section][key + "_set"] = bool(out[section].pop(key, ""))
    return out


def save(changes: dict) -> dict:
    """Merge changes in. A secret left blank keeps the saved one."""
    with _lock:
        cfg = load()
        for k in ("every_hours", "min_score"):
            if k in changes:
                lo, hi = (1, 48) if k == "every_hours" else (0, 100)
                try:
                    cfg[k] = max(lo, min(hi, int(changes[k])))
                except (TypeError, ValueError):
                    raise ValueError(f"{k} must be a number.") from None
        for section in ("searches", "usajobs", "adzuna", "email"):
            for k, v in (changes.get(section) or {}).items():
                if k not in DEFAULT[section] or (section, k) in SECRETS and not v:
                    continue
                if k == "keywords":
                    v = [s.strip() for s in (v.split("\n") if isinstance(v, str) else v) if str(s).strip()][:10]
                elif k in ("radius_miles", "port"):
                    v = int(v or DEFAULT[section][k])
                elif k == "enabled":
                    v = bool(v)
                else:
                    v = str(v).strip()[:300]
                cfg[section][k] = v
        if "nearby" in changes:
            cfg["nearby"] = changes["nearby"]
        if "auto_boards" in changes:
            cfg["auto_boards"] = bool(changes["auto_boards"])
        store.write_json(FILE, cfg)
        return cfg


def autosetup_due(cfg: dict, profile: dict, st: dict, now: datetime | None = None) -> bool:
    """Set Watching up by itself when it's allowed to (auto_boards), the profile has places and roles, and the
    employer list is missing or was made for other places. Tried at most once a day."""
    places = profile.get("locations") or []
    if not cfg.get("auto_boards") or not places or not profile.get("target_titles"):
        return False
    near = cfg.get("nearby") or {}
    if near and near.get("places") == places:
        return False
    last = st.get("autosetup_at")
    now = now or datetime.now(timezone.utc)
    return not last or now - datetime.fromisoformat(last) >= timedelta(hours=AUTO_RETRY_HOURS)


def watch_confirmed(items: list) -> list:
    """Watch every employer board that was confirmed (never one found only by guessing a name). Returns the names added."""
    added = []
    with _lock:
        cfg = load()
        have = {(b["provider"], b["token"].lower()) for b in cfg["boards"]}
        for e in items:
            wb = e.get("watchable")
            if not wb or wb.get("guessed") or wb["provider"] not in feeds.BOARDS or (wb["provider"], wb["token"].lower()) in have:
                continue
            cfg["boards"].append({"provider": wb["provider"], "token": wb["token"], "name": e.get("name") or wb["token"],
                                  "added": jobs.now_iso(), "auto": True})
            have.add((wb["provider"], wb["token"].lower()))
            added.append(e.get("name") or wb["token"])
        if added:
            store.write_json(FILE, cfg)
    return added


def autosetup(profile: dict, find) -> dict:
    """Find the employers near the profile's places (`find` is nearby.find) and watch every confirmed board.
    Records the attempt in watch_state.json whatever happens, so a failure waits a day before trying again."""
    st = state()
    st["autosetup_at"] = jobs.now_iso()
    store.write_json(STATE, st)
    places = profile.get("locations") or []
    items = find(places, profile.get("target_titles") or [], profile.get("skills") or [])
    save({"nearby": {"at": jobs.now_iso(), "places": places, "items": items}})
    added = watch_confirmed(items)
    st = state()
    st["autosetup"] = {"at": jobs.now_iso(), "employers": len(items), "watched": added}
    store.write_json(STATE, st)
    return st["autosetup"]


def add_board(provider: str, token: str, name: str = "") -> dict:
    if provider not in feeds.BOARDS or not token:
        raise ValueError("That isn't a Greenhouse, Lever, Ashby or SmartRecruiters board.")
    with _lock:
        cfg = load()
        if not any(b["provider"] == provider and b["token"].lower() == token.lower() for b in cfg["boards"]):
            cfg["boards"].append({"provider": provider, "token": token, "name": name or token, "added": jobs.now_iso()})
            store.write_json(FILE, cfg)
        return cfg


def remove_board(provider: str, token: str) -> dict:
    with _lock:
        cfg = load()
        cfg["boards"] = [b for b in cfg["boards"] if not (b["provider"] == provider and b["token"] == token)]
        store.write_json(FILE, cfg)
        return cfg


def state() -> dict:
    return store.read_json(STATE, {"sources": {}, "news": [], "mail_done": []})


def _wanted(row: dict, profile: dict, min_score: int) -> bool:
    """Worth adding: in one of their places (or remote, if they take remote work) and a fair quick score."""
    places = profile.get("locations") or []
    loc = row.get("location") or ""
    remote = row.get("remote") == "remote" or "remote" in loc.lower()
    if places and not scoring._place_match(loc, places) and not (remote and "remote" in (profile.get("remote") or [])):
        return False
    probe = {**row, "description": row.get("description") or row.get("_snippet") or ""}
    return scoring.score(probe, profile)["score"] >= min_score


def sources(cfg: dict, profile: dict) -> list:
    """(id, label, fetch) for everything set up, where fetch(want) returns rows."""
    out = []
    for b in cfg["boards"]:
        out.append((f"board:{b['provider']}:{b['token']}", f"{b['name']} ({feeds.BOARDS[b['provider']]})",
                    lambda want, b=b: feeds.fetch_board(b["provider"], b["token"], b["name"], want)))
    words = cfg["searches"]["keywords"] or (profile.get("target_titles") or [])[:5]
    where = cfg["searches"]["where"] or next(iter(profile.get("locations") or []), "")
    radius = cfg["searches"]["radius_miles"]
    u, a = cfg["usajobs"], cfg["adzuna"]
    if u["enabled"] and u["key"] and u["email"] and words:
        out.append(("usajobs", "USAJobs", lambda want: [r for w in words for r in feeds.usajobs(u["key"], u["email"], w, where, radius)]))
    if a["enabled"] and a["app_id"] and a["app_key"] and words:
        out.append(("adzuna", "Adzuna", lambda want: [r for w in words for r in feeds.adzuna(a["app_id"], a["app_key"], w, where, radius)]))
    return out


def run(ledger, profile: dict, only: str | None = None, on_new=None) -> dict:
    """Check every source (or just `only`), add the jobs worth a look, and record how each source went."""
    if not _running.acquire(blocking=False):
        return {"busy": True}
    try:
        cfg, st = load(), state()
        want = lambda row: _wanted(row, profile, cfg["min_score"])  # noqa: E731
        todo = [s for s in sources(cfg, profile) if not only or s[0] == only]
        if cfg["email"]["enabled"] and cfg["email"]["user"] and cfg["email"]["password"] and only in (None, "email"):
            todo.append(("email", "Job alert emails", None))
        new_keys = []
        for sid, label, fetch in todo:
            entry = {"label": label, "at": jobs.now_iso(), "ok": True, "error": "", "found": 0, "kept": 0, "added": 0}
            try:
                if sid == "email":
                    done = set(st.get("mail_done") or [])
                    rows, read = mail.fetch_alerts(cfg["email"], done=done)
                    st["mail_done"] = (list(done) + read)[-2000:]
                    kept = rows  # the person chose these alerts: keep them all
                else:
                    rows = fetch(want)
                    kept = [r for r in rows if want(r)]
                for r in kept:
                    r.pop("_snippet", None)
                    r["found_by"] = label
                before = set(ledger.jobs)
                res = ledger.add(kept, profile) if kept else {"added": 0, "alerts": []}
                added = [f"{r['source']}:{r['id']}" for r in kept if f"{r['source']}:{r['id']}" not in before]
                new_keys += added
                entry.update(found=len(rows), kept=len(kept), added=len(added))
                for a in res.get("alerts") or []:
                    st["news"] = (st.get("news") or [])[-50:] + [{**a, "at": jobs.now_iso(), "via": label}]
            except (feeds.FeedError, mail.MailError) as e:
                entry.update(ok=False, error=str(e))
            st.setdefault("sources", {})[sid] = entry
        st["last_run"] = jobs.now_iso()
        store.write_json(STATE, st)
        if on_new and new_keys:
            on_new(new_keys)
        return st
    finally:
        _running.release()


def due(now: datetime | None = None) -> bool:
    last = state().get("last_run")
    if not last:
        return True
    hours = load()["every_hours"]
    return (now or datetime.now(timezone.utc)) - datetime.fromisoformat(last) >= timedelta(hours=hours)


def start(ledger, get_profile, on_new=None, tick: int = 60) -> threading.Thread:
    """The schedule: a background thread that runs every source when it's due, while the app is running."""
    def loop():
        time.sleep(15)  # let the app finish starting
        while True:
            try:
                cfg = load()
                if (cfg["boards"] or cfg["usajobs"]["enabled"] or cfg["adzuna"]["enabled"] or cfg["email"]["enabled"]) and due():
                    run(ledger, get_profile(), on_new=on_new)
            except Exception as e:  # a bad run must never stop the schedule
                print(f"Watching: {e}")
            time.sleep(tick)
    t = threading.Thread(target=loop, name="watch", daemon=True)
    t.start()
    return t
