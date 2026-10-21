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
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import facts, groups, scoring, store

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
        for rec in self.jobs.values():  # jobs saved before facts were read
            if "facts" not in rec:
                rec["facts"] = facts.of(rec)
        self.group_of, self.members = {}, {}
        self._index()

    def _index(self) -> None:
        """Find each job's copies (the same job on other sites, or relisted) and flag reposts."""
        group_of = groups.build(self.jobs)
        members = defaultdict(list)
        for k, g in group_of.items():
            members[g].append(k)
        for key, rec in self.jobs.items():
            g = group_of.get(key)
            groups.annotate(rec, groups.reposts([self.jobs[k] for k in members[g]] if g else [rec]))
        self.group_of, self.members = group_of, dict(members)

    def copies(self, rec: dict) -> list:
        g = self.group_of.get(rec["key"])
        return [self.jobs[k] for k in self.members.get(g, []) if k != rec["key"] and k in self.jobs] if g else []

    def mark(self, rec: dict) -> dict:
        """mark_for, plus the status you gave one of its copies (applied on LinkedIn shows on the Indeed card)."""
        m = mark_for(rec)
        if not m["status"]:
            for c in self.copies(rec):
                if c.get("status") and c["status"] != "dismissed":
                    m["status"], m["status_on"] = c["status"], SOURCES.get(c["source"], c["source"])
                    break
        return m

    def public(self, rec: dict) -> dict:
        out = public(rec)
        out["copies"] = [{"key": c["key"], "source": c["source"], "source_name": SOURCES.get(c["source"], c["source"]),
                          "url": c.get("url"), "status": c.get("status") or "", "first_seen": c.get("first_seen")}
                         for c in self.copies(rec)]
        m = self.mark(rec)
        if m.get("status_on"):
            out["copy_status"] = {"status": m["status"], "on": m["status_on"]}
        return out

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
        marks, alerts, touched = [], [], []
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
                _posting_date(rec)
                touched.append((rec, is_new, before))
            self._index()
            for rec, is_new, before in touched:
                m = self.mark(rec)
                m["new"] = is_new
                marks.append(m)
                after = rec["rules"]["score"]
                # a copy of a job you've already been told about isn't news
                if (is_new or (before is not None and before < 80 <= after)) and m["score"] >= 80 and not (is_new and self.copies(rec)):
                    alerts.append({"title": rec.get("title"), "company": rec.get("company"), "url": rec.get("url"),
                                   "score": m["score"], "verdict": m["verdict"]})
            self.save()
        return {"added": added, "updated": updated, "marks": marks, "alerts": alerts[:5]}

    def update(self, key: str, changes: dict) -> dict:
        with _lock:
            rec = self.jobs.get(key)
            if rec is None:
                raise KeyError(key)
            applied_now = False
            if "status" in changes:
                st = str(changes["status"] or "")
                if st not in STATUSES:
                    raise ValueError("Unknown status.")
                if st != rec.get("status"):
                    rec["status"] = st
                    rec.setdefault("history", []).append({"at": now_iso(), "status": st})
                    applied_now = st == "applied"
            for k in ("notes",):
                if k in changes:
                    rec[k] = str(changes[k] or "")[:5000]
            for k in ("applied_at", "follow_up"):
                if k in changes:
                    v = str(changes[k] or "")
                    if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                        raise ValueError(f"{k} must be a date (YYYY-MM-DD).")
                    if v or not applied_now:  # the job page's form sends blank dates along with a new status
                        rec[k] = v
            if applied_now:
                rec["applied_at"] = rec.get("applied_at") or now_iso()[:10]
                rec["applied_score"] = best(rec)["score"]  # what it scored when you applied, for your results
                if not rec.get("follow_up"):
                    rec["follow_up"] = (date.fromisoformat(rec["applied_at"]) + timedelta(days=follow_up_days())).isoformat()
            rec["updated"] = now_iso()
            self.save()
            return rec

    def set_analysis(self, key: str, analysis: dict, profile_fp: str) -> dict:
        with _lock:
            rec = self.jobs[key]
            rec["ai"] = {**analysis, "at": now_iso(), "profile": profile_fp, "desc": desc_hash(rec)}
            self.save()
            return rec

    def set_letter(self, key: str, letter: str) -> dict:
        return self.set_field(key, "cover_letter", {"text": letter, "at": now_iso()})

    def set_field(self, key: str, field: str, value) -> dict:
        with _lock:
            rec = self.jobs[key]
            rec[field] = value
            self.save()
            return rec

    def delete(self, key: str) -> None:
        with _lock:
            self.jobs.pop(key, None)
            self._index()
            self.save()

    def rescore_all(self, profile: dict) -> int:
        with _lock:
            for rec in self.jobs.values():
                rescore(rec, profile)
            self._index()
            self.save()
            return len(self.jobs)

    def clear(self, keep_tracked: bool = True) -> int:
        with _lock:
            before = len(self.jobs)
            self.data["jobs"] = {k: r for k, r in self.jobs.items() if keep_tracked and r.get("status")} if keep_tracked else {}
            self._index()
            self.save()
            return before - len(self.jobs)

    def listing(self, q: dict) -> list:
        """Jobs for the app's list, filtered and sorted. q: source, status, verdict, text, sort, and the posting's
        facts: remote (remote|hybrid|onsite), min_pay (listed pay reaches it), max_years (asks for at most that
        many), degree (needs at most that degree), clearance (none | obtainable). A job posted on several sites is
        listed once, by its best-scoring copy, unless q has dupes."""
        recs = list(self.jobs.values())
        if q.get("remote") in ("remote", "hybrid", "onsite"):
            recs = [r for r in recs if (r.get("rules") or {}).get("remote") == q["remote"]]
        min_pay = _num(q.get("min_pay"))
        if min_pay:
            recs = [r for r in recs if ((r.get("rules") or {}).get("pay_max") or 0) >= min_pay]
        max_years = _num(q.get("max_years"))
        if max_years is not None:
            recs = [r for r in recs if (_years(r) or 0) <= max_years]
        if q.get("degree") in facts.DEGREES:
            recs = [r for r in recs if facts.degree_ok((r.get("facts") or {}).get("degree"), q["degree"])]
        if q.get("clearance") == "none":
            recs = [r for r in recs if not (r.get("facts") or {}).get("clearance")]
        elif q.get("clearance") == "obtainable":
            recs = [r for r in recs if not ((r.get("facts") or {}).get("clearance") or {}).get("must_hold")]
        if q.get("source"):
            recs = [r for r in recs if r["source"] == q["source"]]
        st = q.get("status")
        if st == "tracked":
            recs = [r for r in recs if r.get("status") and r["status"] != "dismissed"]
        elif st == "untracked":  # a job you're tracking on another site counts as tracked here too
            recs = [r for r in recs if not r.get("status") and not any(c.get("status") for c in self.copies(r))]
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
        elif sort == "years":
            recs.sort(key=lambda r: (_years(r) is None, _years(r) or 0, -best(r)["score"]))
        else:
            recs.sort(key=lambda r: (best(r)["score"], r.get("last_seen") or ""), reverse=True)
        if not q.get("dupes"):
            shown, out = set(), []
            for r in recs:
                g = self.group_of.get(r["key"])
                if g in shown:
                    continue
                if g:
                    shown.add(g)
                out.append(r)
            recs = out
        return recs

    def csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["source", "title", "company", "location", "arrangement", "pay_text", "years_required", "degree",
                "clearance", "score", "verdict", "ai_fit", "status", "applied_at", "follow_up", "url", "first_seen",
                "last_seen", "notes"]
        w.writerow(cols)
        for r in self.listing({"sort": "score", "all": True}):
            b = best(r)
            f = r.get("facts") or {}
            w.writerow([SOURCES.get(r["source"], r["source"]), r.get("title"), r.get("company"), r.get("location"),
                        (r.get("rules") or {}).get("remote", ""), r.get("pay_text"), _years(r) or "",
                        facts.labels({"degree": f.get("degree")})[0] if f.get("degree") else "",
                        facts.labels({"clearance": f.get("clearance")})[0] if f.get("clearance") else "",
                        b["score"], b["verdict"], (r.get("ai") or {}).get("fit_score", ""),
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


def follow_up_days() -> int:
    try:
        return max(1, min(60, int(store.settings().get("follow_up_days", 10))))
    except (TypeError, ValueError):
        return 10


def _posting_date(rec: dict) -> None:
    """Remember when the site says the job went up; a date that jumps forward a week or more is a repost."""
    age = (rec.get("rules") or {}).get("age_days")
    if age is None:
        return
    posted = (datetime.now(timezone.utc).date() - timedelta(days=age)).isoformat()
    was = rec.get("posted_on")
    if was and (date.fromisoformat(posted) - date.fromisoformat(was)).days >= groups.REPOST_GAP_DAYS:
        rec["reposts"] = int(rec.get("reposts") or 0) + 1
    if not was or posted > was:
        rec["posted_on"] = posted


def rescore(rec: dict, profile: dict) -> None:
    rec["facts"] = facts.of(rec)
    rec["rules"] = scoring.score(rec, profile)


def _years(rec: dict):
    return ((rec.get("facts") or {}).get("years") or {}).get("required")


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


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
    out["fact_tags"] = facts.labels(rec.get("facts") or {})
    out["source_name"] = SOURCES.get(rec["source"], rec["source"])
    return out
