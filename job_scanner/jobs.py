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
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from . import facts, learn, scoring, signals, store

FILE = "jobs.json"
STATUSES = ("", "saved", "applied", "interviewing", "offer", "rejected", "withdrawn", "dismissed")
SOURCES = {"linkedin": "LinkedIn", "indeed": "Indeed", "ncworks": "NCWorks", "greenhouse": "Greenhouse",
           "lever": "Lever", "workday": "Workday", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters",
           "usajobs": "USAJobs", "adzuna": "Adzuna", "jobsnow": "JOBS.NOW", "web": "Other site"}
TEXT_FIELDS = {"title": 300, "company": 200, "location": 200, "pay_text": 200, "job_type": 100, "posted_text": 100,
               "description": 30000, "url": 1000, "found_by": 120}
_lock = threading.RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# LinkedIn's job-match lines ("Your profile and resume match the required qualifications well"), never a job title
NOT_A_TITLE = re.compile(r"(?i)^(your profile|your (skills|experience|resume)|you('d| would) be|you're|you are|you have|you meet|"
                         r"job match|how you match)\b|\b(match(es)?|meet(s)?) (the |all |most |some )?(required |preferred )?"
                         r"(qualifications|requirements)\b")
FOLLOWERS = re.compile(r"(?i)\s*[\d.,]+\s*[km]?\s+followers?\b.*$")


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
    if row.get("title") and NOT_A_TITLE.search(row["title"]):
        row.pop("title")  # a site's match banner read as the title: keep the one already known
    if row.get("company"):
        row["company"] = FOLLOWERS.sub("", row["company"].replace("&amp;", "&")).strip()
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

    @property
    def jobs(self) -> dict:
        return self.data["jobs"]

    def save(self) -> None:
        store.write_json(FILE, self.data)

    def get(self, key: str) -> dict | None:
        return self.jobs.get(key)

    # -- the same job on several sites --
    def index(self) -> dict:
        idx = {}
        for r in self.jobs.values():
            k = signals.dupe_key(r)
            if k:
                idx.setdefault(k, []).append(r)
        return idx

    def siblings(self, rec: dict, idx: dict | None = None) -> list:
        """Other records of the same job: same company and title, and not in two different places."""
        k = signals.dupe_key(rec)
        if not k:
            return []
        group = (idx if idx is not None else self.index()).get(k, [])
        here = signals.place_of(rec.get("location"))
        return [r for r in group if r is not rec and r["key"] != rec["key"]
                and (not here or not signals.place_of(r.get("location")) or signals.place_of(r.get("location")) == here)]

    def public(self, rec: dict, idx: dict | None = None) -> dict:
        return public(rec, self.siblings(rec, idx))

    def mark(self, rec: dict, idx: dict | None = None) -> dict:
        return mark_for(rec, siblings=self.siblings(rec, idx))

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
                note_posted(rec)
                touched.append((rec, is_new, before))
            idx = self.index()
            for rec, is_new, before in touched:
                m = self.mark(rec, idx)
                m["new"] = is_new
                marks.append(m)
                after = rec["rules"]["score"]
                # one alert per job, not one per site it's posted on
                dupe = is_new and any(o.get("first_seen", "") < rec["first_seen"] for o in self.siblings(rec, idx))
                if (is_new and not dupe) or (before is not None and before < 80 <= after):
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
                    if st == "applied" and not rec.get("applied_score"):
                        rec["applied_score"] = best(rec)  # what it was rated when you applied, to check the ratings later
            for k, n in (("notes", 5000), ("contact", 300)):
                if k in changes:
                    rec[k] = str(changes[k] or "")[:n]
            if "done" in changes:  # a tracker to-do the person has dealt with (or dismissed)
                nid = str(changes["done"])[:80]
                rec["done"] = [d for d in rec.get("done", []) if d != nid] + [nid]
            for k in ("applied_at", "follow_up", "interview_at"):
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

    def set_doc(self, key: str, field: str, doc: dict) -> dict:
        """Something Claude wrote for this job: a tailored résumé, or a follow-up or thank-you message."""
        with _lock:
            rec = self.jobs[key]
            rec[field] = {**doc, "at": now_iso()}
            self.save()
            return rec

    def set_letter(self, key: str, letter: str, resume: str = "") -> dict:
        with _lock:
            rec = self.jobs[key]
            rec["cover_letter"] = {"text": letter, "at": now_iso(), "resume": resume}
            self.save()
            return rec

    def set_triage(self, looks: dict) -> None:
        """Claude's first look at postings ({key: {fit_score, verdict, why}}), used to pick which get a full read."""
        with _lock:
            for k, v in looks.items():
                if k in self.jobs:
                    self.jobs[k]["triage"] = {**v, "at": now_iso()}
            self.save()

    def mark_pushed(self, keys: list) -> None:
        """Remember which jobs reached the phone, so each is sent once."""
        with _lock:
            for k in keys:
                if k in self.jobs:
                    self.jobs[k]["pushed"] = now_iso()
            self.save()

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
        """Jobs for the app's list, filtered and sorted. q: source, status, verdict, text, sort, and the posting's
        facts: remote (remote|hybrid|onsite), min_pay (listed pay reaches it), max_years (asks for at most that
        many), degree (needs at most that degree), clearance (none | obtainable)."""
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
        if not q.get("dupes"):
            recs = collapse(recs, self.index())
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
        if q.get("fresh"):
            recs = [r for r in recs if fresh(r)]
        if q.get("drafted"):
            recs = [r for r in recs if r.get("overnight")]
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
        return recs

    def for_page(self, url: str, days: int = 3) -> dict | None:
        """The job an application form belongs to: the posting itself, one whose id is in the form's address, or
        else the job Easy apply was last used on in the past few days."""
        u = urlparse(url or "")
        here = (u.netloc.lower().removeprefix("www.") + u.path.rstrip("/")).lower()
        full = (url or "").lower()
        recs = list(self.jobs.values())
        for r in recs:
            ru = urlparse(r.get("url") or "")
            there = (ru.netloc.lower().removeprefix("www.") + ru.path.rstrip("/")).lower()
            if there and (here == there or here.startswith(there + "/")):
                return r
        for r in recs:
            jid = str(r.get("id") or "").lower()
            if len(jid) >= 6 and re.search(r"(?<![0-9a-z])" + re.escape(jid) + r"(?![0-9a-z])", full):
                return r
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = [r for r in recs if (r.get("packet") or {}).get("at", "") >= cutoff.isoformat(timespec="seconds")]
        return max(recent, key=lambda r: r["packet"]["at"]) if recent else None

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


def _rank(r: dict) -> tuple:
    """Which copy of a job to show: the one you're tracking, then the one Claude read, then the fullest."""
    return (bool(r.get("status") and r["status"] != "dismissed"), bool(r.get("ai")), bool(r.get("description")),
            r.get("last_seen") or "")


def collapse(recs: list, idx: dict) -> list:
    """One record per job: copies of the same job on other sites are folded into the best one."""
    out, hidden = [], set()
    for r in sorted(recs, key=_rank, reverse=True):
        if r["key"] in hidden:
            continue
        out.append(r)
        k = signals.dupe_key(r)
        if not k:
            continue
        here = signals.place_of(r.get("location"))
        for o in idx.get(k, []):
            there = signals.place_of(o.get("location"))
            if o is not r and (not here or not there or here == there):
                hidden.add(o["key"])
    return out


def note_posted(rec: dict, today=None) -> None:
    """Remember the day the site says the job went up. If a later capture puts that a week or more later, the job
    was reposted under the same id (counted in rec["reposts"], read by signals.relisted)."""
    age = (rec.get("rules") or {}).get("age_days")
    if age is None:
        return
    today = today or datetime.now(timezone.utc).date()
    posted = (today - timedelta(days=int(age))).isoformat()
    was = rec.get("posted_on")
    if was and (date.fromisoformat(posted) - date.fromisoformat(was)).days >= signals.REPOST_GAP_DAYS:
        rec["reposts"] = int(rec.get("reposts") or 0) + 1
    if not was or posted > was:
        rec["posted_on"] = posted


FRESH_DAYS = 1  # posted today or yesterday


def fresh(rec: dict, today=None) -> bool:
    """Posted today or yesterday (by the posting date the site gave), and still open: the jobs worth applying to
    first. Read from posted_on, so it goes stale on its own as days pass."""
    if rec.get("closed") or not rec.get("posted_on"):
        return False
    today = today or datetime.now(timezone.utc).date()
    try:
        return (today - date.fromisoformat(rec["posted_on"])).days <= FRESH_DAYS
    except ValueError:
        return False


def merge(rec: dict, row: dict) -> None:
    """Fold a newly captured row into its record. A full posting's fields win over a card's; a card never wipes
    out a description that was captured from the posting itself."""
    for k, v in row.items():
        if k in ("source", "id", "kind"):
            continue
        if k == "description" and len(v) < len(rec.get("description") or "") * 0.5:
            continue
        if row["kind"] == "card" and (rec.get("opened") or row.get("found_by")) and k in ("title", "company", "location") and rec.get(k):
            continue  # an alert email or feed card never relabels a job you've already seen
        if v in ("", None) and rec.get(k):
            continue  # a card that leaves a field out doesn't blank what's known
        rec[k] = v
    if row["kind"] == "item":
        rec["opened"] = now_iso()
    rec["last_seen"] = now_iso()
    rec["seen"] = rec.get("seen", 0) + 1


def desc_hash(rec: dict) -> str:
    return hashlib.sha256((rec.get("description") or "").encode()).hexdigest()[:12]


def rescore(rec: dict, profile: dict) -> None:
    rec["facts"] = facts.of(rec)
    r = scoring.score(rec, profile)
    rec["rules"] = r
    learn.apply(rec, {w for t in profile.get("target_titles") or [] for w in scoring.words(t)})
    scam = [w["text"] for w in signals.warnings(rec) if w["level"] == "scam"]
    r["scam"] = bool(scam)
    if scam:
        r["cautions"].insert(0, "Signs of a scam: " + scam[0])
        r["score"], r["verdict"] = min(r["score"], 30), scoring.SKIP


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
        if (rec.get("rules") or {}).get("scam"):  # a good fit on paper is no reason to send your details to a scam
            return {"score": min(int(ai["fit_score"]), 30), "verdict": scoring.SKIP, "by": "ai"}
        return {"score": int(ai["fit_score"]), "verdict": ai.get("verdict") or scoring.CONSIDER, "by": "ai"}
    r = rec.get("rules") or {"score": 0, "verdict": scoring.SKIP}
    return {"score": r["score"], "verdict": r["verdict"], "by": "rules"}


def ai_current(rec: dict, profile_fp: str) -> bool:
    ai = rec.get("ai")
    return bool(ai) and ai.get("profile") == profile_fp and ai.get("desc") == desc_hash(rec)


def tracked_status(rec: dict, siblings: list) -> tuple:
    """(status, where): this record's own status, or the one you set on another site's copy of the job."""
    if rec.get("status"):
        return rec["status"], ""
    for o in siblings:
        if o.get("status") and o["status"] != "dismissed":
            return o["status"], SOURCES.get(o["source"], o["source"])
    return "", ""


def mark_for(rec: dict, profile: dict | None = None, siblings: list | None = None) -> dict:
    """What the extension needs to stamp a card or fill its panel."""
    b = best(rec)
    status, via = tracked_status(rec, siblings or [])
    warn = signals.warnings(rec, siblings)
    r = rec.get("rules") or {}
    ai = rec.get("ai") or {}
    why = ai.get("summary") or "; ".join((r.get("reasons") or [])[:3] + (r.get("cautions") or [])[:2])
    return {"source": rec["source"], "id": rec["id"], "key": rec["key"], "score": b["score"], "verdict": b["verdict"],
            "by": b["by"], "why": why, "status": status, "status_via": via, "analyzed": bool(ai),
            "has_description": bool(rec.get("description")), "fresh": fresh(rec), "facts": facts.labels(rec.get("facts") or {}),
            "warnings": [w for w in warn if w["level"] in ("scam", "ghost")][:3]}


def public(rec: dict, siblings: list | None = None) -> dict:
    out = dict(rec)
    out["best"] = best(rec)
    out["source_name"] = SOURCES.get(rec["source"], rec["source"])
    out["fresh"] = fresh(rec)
    out["fact_tags"] = facts.labels(rec.get("facts") or {})
    out["warnings"] = signals.warnings(rec, siblings)
    out["also_on"] = [{"key": o["key"], "source": SOURCES.get(o["source"], o["source"]), "url": o.get("url") or "",
                       "status": o.get("status") or "", "title": o.get("title") or ""} for o in siblings or []]
    st, via = tracked_status(rec, siblings or [])
    if via:
        out["status_elsewhere"] = {"status": st, "where": via}
    return out
