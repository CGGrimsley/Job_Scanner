"""The job ledger: every posting the extension has captured, one merged record per job, in jobs.json.

A job seen as a search card, then opened, then seen again is one record. Each record keeps the rules score, the
latest Claude analysis (with the profile it was made against), and the person's own tracking: status, dates,
notes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import threading
from datetime import datetime, timezone

from . import scoring, store

FILE = "jobs.json"
STATUSES = ("", "saved", "applied", "interviewing", "offer", "rejected", "withdrawn", "dismissed")
SOURCES = {"linkedin": "LinkedIn", "indeed": "Indeed", "ncworks": "NCWorks", "greenhouse": "Greenhouse",
           "lever": "Lever", "workday": "Workday", "web": "Other site"}
TEXT_FIELDS = {"title": 300, "company": 200, "location": 200, "pay_text": 200, "job_type": 100, "posted_text": 100,
               "description": 30000, "url": 1000}
_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _str(v, n: int) -> str:
    return re.sub(r"[ \t ]+", " ", str(v or "")).strip()[:n]


def clean_row(raw: dict) -> dict | None:
    """One captured job from the extension, checked: a known source, a sane id, text fields trimmed."""
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or "").lower()
    jid = str(raw.get("id") or "")
    if source not in SOURCES or not re.fullmatch(r"[\w.:-]{1,120}", jid):
        return None
    row = {"source": source, "id": jid, "kind": raw.get("kind") if raw.get("kind") in ("card", "item") else "card"}
    for k, n in TEXT_FIELDS.items():
        if raw.get(k):
            row[k] = _str(raw[k], n) if k != "description" else str(raw[k]).strip()[:n]
    if row.get("url") and not row["url"].startswith("https://"):
        row.pop("url")
    for k in ("pay_min", "pay_max", "applicants"):
        v = raw.get(k)
        if isinstance(v, (int, float)) and 0 <= v < 10_000_000:
            row[k] = int(v)
    for k in ("easy_apply", "closed", "applied_on_site", "remote_flag"):
        if isinstance(raw.get(k), bool):
            row[k] = raw[k]
    if raw.get("remote") in ("remote", "hybrid", "onsite"):
        row["remote"] = raw["remote"]
    if isinstance(raw.get("tags"), list):
        row["tags"] = [_str(t, 60) for t in raw["tags"][:12] if t]
    if not row.get("title") and row["kind"] == "card":
        return None
    return row


class Ledger:
    def __init__(self):
        self.data = store.read_json(FILE, {"jobs": {}})
        self.data.setdefault("jobs", {})

    @property
    def jobs(self) -> dict:
        return self.data["jobs"]

    def save(self) -> None:
        store.write_json(FILE, self.data)

    def get(self, key: str) -> dict | None:
        return self.jobs.get(key)

    def add(self, rows: list, profile: dict) -> dict:
        """Merge captured rows in and score them. Returns counts and a mark per row for the page's stamps."""
        added = updated = 0
        marks, alerts = [], []
        with _lock:
            for raw in rows:
                row = clean_row(raw)
                if not row:
                    continue
                key = f"{row['source']}:{row['id']}"
                rec = self.jobs.get(key)
                if rec is None:
                    rec = self.jobs[key] = {"key": key, "source": row["source"], "id": row["id"], "first_seen": now_iso(),
                                            "status": "", "notes": ""}
                    added += 1
                    is_new = True
                else:
                    updated += 1
                    is_new = False
                before = (rec.get("rules") or {}).get("score")
                merge(rec, row)
                rescore(rec, profile)
                m = mark_for(rec, profile)
                m["new"] = is_new
                marks.append(m)
                after = rec["rules"]["score"]
                if is_new or (before is not None and before < 80 <= after):
                    if m["score"] >= 80:
                        alerts.append({"title": rec.get("title"), "company": rec.get("company"), "url": rec.get("url"),
                                       "score": m["score"], "verdict": m["verdict"]})
            self.save()
        return {"added": added, "updated": updated, "marks": marks, "alerts": alerts[:5]}

    def update(self, key: str, changes: dict) -> dict:
        with _lock:
            rec = self.jobs.get(key)
            if rec is None:
                raise KeyError(key)
            if "status" in changes:
                st = str(changes["status"] or "")
                if st not in STATUSES:
                    raise ValueError("Unknown status.")
                if st != rec.get("status"):
                    rec["status"] = st
                    rec.setdefault("history", []).append({"at": now_iso(), "status": st})
                    if st == "applied" and not rec.get("applied_at"):
                        rec["applied_at"] = now_iso()[:10]
            for k in ("notes",):
                if k in changes:
                    rec[k] = str(changes[k] or "")[:5000]
            for k in ("applied_at", "follow_up"):
                if k in changes:
                    v = str(changes[k] or "")
                    if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                        raise ValueError(f"{k} must be a date (YYYY-MM-DD).")
                    rec[k] = v
            rec["updated"] = now_iso()
            self.save()
            return rec

    def set_analysis(self, key: str, analysis: dict, profile_fp: str) -> dict:
        with _lock:
            rec = self.jobs[key]
            rec["ai"] = {**analysis, "at": now_iso(), "profile": profile_fp, "desc": desc_hash(rec)}
            self.save()
            return rec

    def set_letter(self, key: str, letter: str, resume: str = "") -> dict:
        with _lock:
            rec = self.jobs[key]
            rec["cover_letter"] = {"text": letter, "at": now_iso(), "resume": resume}
            self.save()
            return rec

    def delete(self, key: str) -> None:
        with _lock:
            self.jobs.pop(key, None)
            self.save()

    def rescore_all(self, profile: dict) -> int:
        with _lock:
            for rec in self.jobs.values():
                rescore(rec, profile)
            self.save()
            return len(self.jobs)

    def clear(self, keep_tracked: bool = True) -> int:
        with _lock:
            before = len(self.jobs)
            self.data["jobs"] = {k: r for k, r in self.jobs.items() if keep_tracked and r.get("status")} if keep_tracked else {}
            self.save()
            return before - len(self.jobs)

    def listing(self, q: dict) -> list:
        """Jobs for the app's list, filtered and sorted. q: source, status, verdict, text, sort."""
        recs = list(self.jobs.values())
        if q.get("source"):
            recs = [r for r in recs if r["source"] == q["source"]]
        st = q.get("status")
        if st == "tracked":
            recs = [r for r in recs if r.get("status") and r["status"] != "dismissed"]
        elif st == "untracked":
            recs = [r for r in recs if not r.get("status")]
        elif st:
            recs = [r for r in recs if r.get("status") == st]
        elif not q.get("all"):
            recs = [r for r in recs if r.get("status") != "dismissed"]
        if q.get("verdict"):
            recs = [r for r in recs if best(r)["verdict"] == q["verdict"]]
        if q.get("text"):
            t = q["text"].lower()
            recs = [r for r in recs if t in " ".join(str(r.get(k) or "") for k in ("title", "company", "location")).lower()]
        sort = q.get("sort") or "score"
        if sort == "newest":
            recs.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
        elif sort == "pay":
            recs.sort(key=lambda r: (r.get("rules") or {}).get("pay_max") or 0, reverse=True)
        elif sort == "follow_up":
            recs.sort(key=lambda r: r.get("follow_up") or "9999")
        else:
            recs.sort(key=lambda r: (best(r)["score"], r.get("last_seen") or ""), reverse=True)
        return recs

    def csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["source", "title", "company", "location", "pay_text", "score", "verdict", "ai_fit", "status",
                "applied_at", "follow_up", "url", "first_seen", "last_seen", "notes"]
        w.writerow(cols)
        for r in self.listing({"sort": "score", "all": True}):
            b = best(r)
            w.writerow([SOURCES.get(r["source"], r["source"]), r.get("title"), r.get("company"), r.get("location"),
                        r.get("pay_text"), b["score"], b["verdict"], (r.get("ai") or {}).get("fit_score", ""),
                        r.get("status"), r.get("applied_at", ""), r.get("follow_up", ""), r.get("url"),
                        r.get("first_seen"), r.get("last_seen"), r.get("notes", "")])
        return buf.getvalue()

    def counts(self) -> dict:
        c = {"total": len(self.jobs), "analyzed": 0, "by_status": {}}
        for r in self.jobs.values():
            if r.get("ai"):
                c["analyzed"] += 1
            if r.get("status"):
                c["by_status"][r["status"]] = c["by_status"].get(r["status"], 0) + 1
        return c


def merge(rec: dict, row: dict) -> None:
    """Fold a newly captured row into its record. A full posting's fields win over a card's; a card never wipes
    out a description that was captured from the posting itself."""
    for k, v in row.items():
        if k in ("source", "id", "kind"):
            continue
        if k == "description" and len(v) < len(rec.get("description") or "") * 0.5:
            continue
        if row["kind"] == "card" and rec.get("opened") and k in ("title", "company", "location") and rec.get(k):
            continue
        rec[k] = v
    if row["kind"] == "item":
        rec["opened"] = now_iso()
    rec["last_seen"] = now_iso()
    rec["seen"] = rec.get("seen", 0) + 1


def desc_hash(rec: dict) -> str:
    return hashlib.sha256((rec.get("description") or "").encode()).hexdigest()[:12]


def rescore(rec: dict, profile: dict) -> None:
    rec["rules"] = scoring.score(rec, profile)


def best(rec: dict) -> dict:
    """The score to show: Claude's fit score when there is one, else the rules score."""
    ai = rec.get("ai")
    if ai and isinstance(ai.get("fit_score"), (int, float)):
        return {"score": int(ai["fit_score"]), "verdict": ai.get("verdict") or scoring.CONSIDER, "by": "ai"}
    r = rec.get("rules") or {"score": 0, "verdict": scoring.SKIP}
    return {"score": r["score"], "verdict": r["verdict"], "by": "rules"}


def ai_current(rec: dict, profile_fp: str) -> bool:
    ai = rec.get("ai")
    return bool(ai) and ai.get("profile") == profile_fp and ai.get("desc") == desc_hash(rec)


def mark_for(rec: dict, profile: dict | None = None) -> dict:
    """What the extension needs to stamp a card or fill its panel."""
    b = best(rec)
    r = rec.get("rules") or {}
    ai = rec.get("ai") or {}
    why = ai.get("summary") or "; ".join((r.get("reasons") or [])[:3] + (r.get("cautions") or [])[:2])
    return {"source": rec["source"], "id": rec["id"], "key": rec["key"], "score": b["score"], "verdict": b["verdict"],
            "by": b["by"], "why": why, "status": rec.get("status") or "", "analyzed": bool(ai),
            "has_description": bool(rec.get("description"))}


def public(rec: dict) -> dict:
    out = dict(rec)
    out["best"] = best(rec)
    out["source_name"] = SOURCES.get(rec["source"], rec["source"])
    return out
