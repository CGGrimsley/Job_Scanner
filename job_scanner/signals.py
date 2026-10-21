"""Warning signs on a posting, found without AI: likely scams, ghost jobs (postings that stay up, or keep coming
back, with no real opening behind them), missing pay where the law asks for it, and thin postings.

Each warning is {"code", "level", "text"}. Levels: "scam" (signs of fraud; the score is capped), "ghost" (it may
not be a live opening), "caution" (worth knowing before you spend time on it) and "info". They only say what the
posting shows, never more: a warning is a reason to look closer, not a verdict.
"""

from __future__ import annotations

import re

from . import scoring
from .places import STATE_CODES, US_STATES

LEVELS = ("scam", "ghost", "caution", "info")

# States where most employers must put a pay range in job postings (thresholds vary by employer size).
PAY_TRANSPARENCY = {"CA", "CO", "WA", "NY", "IL", "MD", "MN", "VT", "MA", "NJ", "HI", "DC"}

SCAM = [
    (r"\b(telegram|whats ?app|signal app|wickr|google hangouts?)\b", "Asks you to talk over a chat app (Telegram, WhatsApp…), a common scam move"),
    (r"\b(text|sms)\b[^.\n]{0,40}\b(\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4})", "Asks you to text a phone number to apply"),
    (r"[\w.+-]+@(gmail|yahoo|hotmail|outlook|aol|proton(mail)?|icloud)\.com", "The contact address is a personal email (Gmail, Yahoo…), not a company one"),
    (r"\b(check|funds?)\b[^.\n]{0,60}\b(equipment|supplies|office setup|home office)\b|\b(purchase|buy)\b[^.\n]{0,40}\bequipment\b[^.\n]{0,60}\b(reimburs|vendor)",
     "Mentions sending you money or a check to buy equipment, a classic fake-job scam"),
    (r"\b(gift cards?|bitcoin|crypto(currency)? (wallet|payment)|wire (the )?(money|funds)|money ?gram|western union)\b",
     "Talks about gift cards, crypto or wiring money"),
    (r"\b(reship(ping)?|package (forwarding|inspector)|parcel forwarding)\b", "Describes reshipping packages, a known scam"),
    (r"\b(training|application|registration|starter kit|background check) fee\b|\bpay (a|the) (small )?fee\b",
     "Asks you to pay a fee to start"),
    (r"\b(no interview( required| needed)?|hired (on the spot|immediately) without)\b", "Promises hiring with no interview"),
    (r"\b(send|provide)\b[^.\n]{0,40}\b(ssn|social security( number)?|bank (account|details)|routing number)\b",
     "Asks for your Social Security or bank details before an offer"),
]
STAFFING = r"\b(on behalf of (our|a) client|our client( is| has|,)|staffing (agency|firm)|recruiting (agency|firm)|contract[- ]to[- ]hire through)\b"
REPOST_GAP_DAYS = 7
EVERGREEN = r"\b(always (accepting|hiring|looking)|evergreen|talent (pool|community|pipeline)|future (opportunities|openings)|general application)\b"


def state_of(location: str) -> str:
    loc = location or ""
    m = re.search(r",\s*([A-Z]{2})\b", loc)
    if m and m.group(1) in US_STATES:
        return m.group(1)
    low = loc.lower()
    for name, code in STATE_CODES.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return code
    if re.search(r"\b(washington,? d\.?c\.?|district of columbia)\b", low):
        return "DC"
    return ""


def warnings(rec: dict, group: list | None = None) -> list:
    """Warning signs for one job. group: other records of the same job on other sites (see jobs.dupe_key)."""
    out = []
    desc = rec.get("description") or ""
    text = " ".join([rec.get("title") or "", rec.get("pay_text") or "", desc]).lower()
    r = rec.get("rules") or {}

    seen = set()
    for rx, why in SCAM:
        if re.search(rx, text) and why not in seen:
            seen.add(why)
            out.append({"code": "scam", "level": "scam", "text": why})
    hi = r.get("pay_max")
    hourly_rich = hi and hi >= 35 * scoring.HOURS_PER_YEAR
    if hourly_rich and re.search(r"\b(no experience (needed|required|necessary)|entry[- ]level)\b", text) and \
            re.search(r"\b(data entry|typing|assistant|customer service|chat support)\b", text):
        out.append({"code": "too_good", "level": "scam",
                    "text": f"Pays up to ${hi:,} a year for entry-level, no-experience work, which is far above the norm"})

    posted = (rec.get("posted_text") or "").lower()
    age = r.get("age_days")
    again = relisted([rec] + list(group or []))
    if again:
        times = "once" if again["count"] == 1 else f"{again['count']} times"
        out.append({"code": "reposted", "level": "ghost",
                    "text": f"Listed again {times} since you first saw it on {again['since']}. Can mean a ghost job or a hard-to-fill role"})
    elif "repost" in posted:
        out.append({"code": "reposted", "level": "ghost", "text": "Reposted: the same opening has been put up again"})
    if age is not None and age >= 45:
        out.append({"code": "old", "level": "ghost", "text": f"Up for {age} days. Long-open postings are often filled or never real"})
    if re.search(EVERGREEN, text):
        out.append({"code": "evergreen", "level": "ghost",
                    "text": "Reads like a talent pool or always-open posting, not a specific opening"})
    span = _seen_span([rec] + list(group or []))
    if span >= 45 and not any(w["code"] in ("old", "reposted") for w in out):
        out.append({"code": "lingering", "level": "ghost", "text": f"You've seen this job listed for {span} days"})

    state = state_of(rec.get("location") or "")
    if state in PAY_TRANSPARENCY and hi is None and (desc or rec.get("pay_text") is not None):
        name = US_STATES.get(state, state)
        out.append({"code": "no_pay", "level": "caution",
                    "text": f"No pay listed, though most employers must post a range for jobs in {name}. Worth asking about"})
    if rec.get("opened") and desc and len(desc) < 500:
        out.append({"code": "thin", "level": "caution", "text": "Very little detail about the role or its requirements"})
    if re.search(STAFFING, text):
        out.append({"code": "agency", "level": "info", "text": "Posted by a recruiter or staffing agency for an unnamed client"})
    if rec.get("applicants") and rec["applicants"] >= 500:
        out.append({"code": "crowded", "level": "info", "text": f"{rec['applicants']}+ applicants already"})
    return sorted(out, key=lambda w: LEVELS.index(w["level"]))


def relisted(recs: list) -> dict | None:
    """{'count', 'since'} when one job's copies show it was put up again: the same site listing it under a new id a
    week or more after you first saw it, or its posting date jumping forward (counted in jobs.note_posted)."""
    from datetime import datetime

    by_source: dict = {}
    count = 0
    for r in recs:
        by_source.setdefault(r.get("source"), []).append(r.get("first_seen") or "")
        count += int(r.get("reposts") or 0)
    for seen in by_source.values():
        seen = sorted(x for x in seen if x)
        for a, b in zip(seen, seen[1:]):
            try:
                count += (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days >= REPOST_GAP_DAYS
            except ValueError:
                pass
    if not count:
        return None
    return {"count": count, "since": min((r.get("first_seen") or "" for r in recs if r.get("first_seen")), default="")[:10]}


def _seen_span(recs: list) -> int:
    from datetime import datetime

    dates = []
    for r in recs:
        for k in ("first_seen", "last_seen"):
            try:
                dates.append(datetime.fromisoformat(r[k]))
            except (KeyError, TypeError, ValueError):
                pass
    return (max(dates) - min(dates)).days if len(dates) >= 2 else 0


# ---------- the same job on several sites ----------
_COMPANY_NOISE = r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|the|plc|lp|llp|group|holdings)\b"


def norm_company(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    return " ".join(re.sub(_COMPANY_NOISE, " ", n).split())


def norm_title(title: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (title or "").lower())
    t = re.sub(r"\s[-–|]\s.*$", "", t)  # "Data Analyst - Remote", "Analyst | Acme"
    return " ".join(scoring.words(t))


def place_of(location: str) -> str:
    loc = (location or "").lower()
    if not loc or re.search(r"\bremote\b|anywhere|united states$", loc):
        return ""
    return re.sub(r"[^a-z ]+", "", loc.split(",")[0]).strip()


def dupe_key(rec: dict) -> str:
    """company|title: records that share it are one job seen on several sites (place is checked separately)."""
    c, t = norm_company(rec.get("company")), norm_title(rec.get("title"))
    return f"{c}|{t}" if c and t else ""
