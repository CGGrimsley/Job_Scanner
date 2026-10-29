"""Learning from what you do with jobs. Patterns you dismiss again and again (an employer, a word in the title,
staffing agencies, a level, on-site work) become suggestions to score lower; patterns you keep saving and applying
to (an interview counts twice) become suggestions to score higher. Only the ones you approve change scores, by
PENALTY or BOOST points with a note that says why. Nothing is learned silently. Kept in learned.json:
{"rules": [...], "declined": [...]}; a rule that raises scores has "up": true and an id starting "up:".
"""

from __future__ import annotations

import os
import re
import threading

from . import scoring, signals, store

FILE = "learned.json"
MIN_PASSES = 3
MIN_WORD_PASSES = 4
MIN_RATE = 0.75
PENALTY = 12
MIN_KEPT = 3     # saves/applications (interviews count twice) before a pattern is suggested to score higher
BOOST = 6
LIKED = ("saved", "applied", "interviewing", "offer")
KEPT = ("saved", "applied", "interviewing", "offer", "rejected", "withdrawn")
_STOP = {"and", "or", "of", "the", "a", "an", "to", "for", "in", "at", "with", "i", "ii", "iii", "iv", "job", "jobs",
         "position", "role", "remote", "hybrid", "onsite", "full", "time", "part", "new"}
_lock = threading.Lock()
_cache = {"stamp": None, "data": None}


def load() -> dict:
    path = store.path(FILE)
    try:
        stamp = (str(path), os.stat(path).st_mtime_ns)
    except OSError:
        stamp = (str(path), None)
    if _cache["stamp"] != stamp or _cache["data"] is None:
        data = store.read_json(FILE, {})
        data.setdefault("rules", [])
        data.setdefault("declined", [])
        _cache.update(stamp=stamp, data=data)
    return _cache["data"]


def rule_id(kind: str, value: str, up: bool = False) -> str:
    return f"{'up:' if up else ''}{kind}:{value}"


def _rid(x: dict) -> str:
    return rule_id(x["kind"], x["value"], bool(x.get("up")))


def features(rec: dict, targets: set) -> set:
    """(kind, value) pairs a posting has that a pattern could be learned from."""
    out = set()
    c = signals.norm_company(rec.get("company") or "")
    if c:
        out.add(("company", c))
    for w in set(scoring.words(rec.get("title") or "")) - _STOP - targets:
        if len(w) > 2:
            out.add(("title_word", w))
    r = rec.get("rules") or {}
    if r.get("level") in ("senior", "director", "executive", "entry", "intern"):
        out.add(("level", r["level"]))
    if r.get("remote") == "onsite":
        out.add(("arrangement", "onsite"))
    if re.search(signals.STAFFING, " ".join([rec.get("title") or "", rec.get("description") or ""]).lower()):
        out.add(("agency", "yes"))
    return out


UP_KINDS = ("company", "title_word", "level", "arrangement")
LABEL = {"company": "jobs at {display}", "title_word": 'titles with "{display}"', "level": "{display}-level jobs",
         "arrangement": "on-site jobs", "agency": "staffing agency postings"}


def suggestions(recs: list, profile: dict) -> list:
    """Patterns you've passed on at least MIN_PASSES times and at least MIN_RATE of the times you acted on them, and
    patterns you've kept (saved, applied; an interview counts twice) at least MIN_KEPT times at the same rate."""
    targets = {w for t in profile.get("target_titles") or [] for w in scoring.words(t)}
    passes, kept, liked, display = {}, {}, {}, {}
    for r in recs:
        st = r.get("status")
        if st != "dismissed" and st not in KEPT:
            continue
        went_well = st in ("interviewing", "offer") or any(h.get("status") in ("interviewing", "offer") for h in r.get("history") or [])
        for f in features(r, targets):
            if st == "dismissed":
                passes[f] = passes.get(f, 0) + 1
            else:
                kept[f] = kept.get(f, 0) + 1
                if st in LIKED or went_well:
                    liked[f] = liked.get(f, 0) + (2 if went_well else 1)
            if f[0] == "company":
                display.setdefault(f, r.get("company") or f[1])
    data = load()
    have = {_rid(x) for x in data["rules"]} | set(data["declined"])
    out = []
    for f, n in passes.items():
        k = kept.get(f, 0)
        need = MIN_WORD_PASSES if f[0] == "title_word" else MIN_PASSES
        if n < need or n / (n + k) < MIN_RATE or rule_id(*f) in have:
            continue
        label = LABEL[f[0]].format(display=display.get(f, f[1]))
        out.append({"id": rule_id(*f), "kind": f[0], "value": f[1], "label": label, "passed": n, "kept": k, "up": False})
    for f, n in liked.items():
        p = passes.get(f, 0)
        if f[0] not in UP_KINDS or n < MIN_KEPT or n / (n + p) < MIN_RATE or rule_id(*f, up=True) in have:
            continue
        label = LABEL[f[0]].format(display=display.get(f, f[1]))
        out.append({"id": rule_id(*f, up=True), "kind": f[0], "value": f[1], "label": label, "kept": n, "passed": p, "up": True})
    return sorted(out, key=lambda s: -(s["kept"] if s["up"] else s["passed"]))[:8]


def decide(sid: str, accept: bool, label: str = "") -> dict:
    up = sid.startswith("up:")
    kind, _, value = sid[3 if up else 0:].partition(":")
    if kind not in LABEL or not value or (up and kind not in UP_KINDS):
        raise ValueError("Unknown suggestion.")
    with _lock:
        data = dict(load())
        data["rules"] = [x for x in data["rules"] if _rid(x) != sid]
        data["declined"] = [x for x in data["declined"] if x != sid]
        if accept:
            rule = {"kind": kind, "value": value, "label": label[:120] or LABEL[kind].format(display=value)}
            if up:
                rule["up"] = True
            data["rules"].append(rule)
        elif accept is False:
            data["declined"].append(sid)
        store.write_json(FILE, data)
        _cache["stamp"] = None
        return load()


def forget(sid: str) -> dict:
    """Undo an approved rule (it may be suggested again later)."""
    with _lock:
        data = dict(load())
        data["rules"] = [x for x in data["rules"] if _rid(x) != sid]
        store.write_json(FILE, data)
        _cache["stamp"] = None
        return load()


def apply(rec: dict, targets: set | None = None) -> None:
    """Move the quick score of a posting that matches a pattern you approved, and say why."""
    rules = load()["rules"]
    r = rec.get("rules")
    if not rules or not r:
        return
    have = features(rec, targets or set())
    hit = [x for x in rules if (x["kind"], x["value"]) in have]
    if not hit:
        return
    down = [x for x in hit if not x.get("up")]
    up = [x for x in hit if x.get("up")]
    if down:
        r["score"] = max(0, r["score"] - PENALTY)
        r["cautions"].insert(0, "You usually pass on " + "; ".join(x["label"] for x in down[:2]))
    elif up and r["score"] > 25:  # never lifts a job off the avoid list or out of a hard stop
        r["score"] = min(100, r["score"] + BOOST)
        r["reasons"].insert(0, "Like ones you've gone for: " + "; ".join(x["label"] for x in up[:2]))
    r["verdict"] = scoring.APPLY if r["score"] >= 70 else scoring.CONSIDER if r["score"] >= 50 else scoring.SKIP
    r["learned"] = [_rid(x) for x in hit]
