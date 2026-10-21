"""Fast rules scoring: every job card gets a score out of 100 and a verdict, with no AI.

This measures how well a posting matches the person's stated preferences (title, skills mentioned, place, pay,
level), not whether they'd get the job: only Claude's reading of the full posting against the résumé judges that.
The app and extension label it that way.

The parts (title match, skills, location, pay, level, freshness) add up to 100. Anything on the avoid list, or a
level or arrangement the person ruled out, caps the score so it reads Skip. Claude's fit analysis, when there is
one, replaces this score on the stamp; this is the quick first pass on everything you scroll past.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from . import facts

HOURS_PER_YEAR = 2080
APPLY, CONSIDER, SKIP = "Apply", "Consider", "Skip"

STOP = {"and", "or", "the", "a", "an", "of", "for", "to", "in", "at", "with", "on", "i", "ii", "iii", "iv", "-", "&", "/"}
ABBREV = {"sr": "senior", "jr": "junior", "mgr": "manager", "eng": "engineer", "dev": "developer", "admin": "administrator",
          "asst": "assistant", "assoc": "associate", "rep": "representative", "tech": "technician", "spec": "specialist"}

# levels, most specific first; matched against the title
LEVELS = [
    ("intern", r"\b(intern|internship|co-?op)\b"),
    ("executive", r"\b(chief|ceo|cto|cfo|coo|cio|vp|vice president|head of|president)\b"),
    ("director", r"\bdirector\b"),
    ("manager", r"\b(manager|mgr|supervisor)\b"),
    ("lead", r"\b(lead|principal|staff|architect)\b"),
    ("senior", r"\b(senior|sr\.?|iii|iv)\b"),
    ("entry", r"\b(junior|jr\.?|entry[- ]level|associate|trainee|apprentice|graduate|i)\b"),
]


def words(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z0-9+#.]+", (text or "").lower()):
        w = w.strip(".")
        w = ABBREV.get(w, w)
        if w and w not in STOP:
            out.append(w)
    return out


def level_of(title: str) -> str:
    t = (title or "").lower()
    for name, rx in LEVELS:
        if re.search(rx, t):
            return name
    return "mid"


def remote_of(*texts: str) -> str:
    t = " ".join(x for x in texts if x).lower()
    if re.search(r"\bhybrid\b", t):
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh|telecommute|anywhere)\b", t):
        return "remote"
    if re.search(r"\b(on-?site|in[- ]office|in person)\b", t):
        return "onsite"
    return ""


_AMT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?"
_RANGE_TAIL = re.compile(r"(?:\s*/\s*\w+)?\s?(?:-|–|to)\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?([kK])?")


def pay_of(text: str):
    """(min, max) yearly dollars from text like '$50,000 - $65,000 a year', '$22.50/hr', '$85K', else (None, None)."""
    t = text or ""
    found = list(re.finditer(_AMT, t))
    if not found:
        return None, None
    nums = []
    for m in found[:2]:
        n = float(m.group(1).replace(",", ""))
        if m.group(2):
            n *= 1000
        nums.append(n)
    end = found[min(1, len(found) - 1)].end()
    rng = _RANGE_TAIL.match(t, found[0].end())  # "$18 - 20 an hour": the second figure without its own $
    if len(found) == 1 and rng:
        nums.append(float(rng.group(1).replace(",", "")) * (1000 if rng.group(2) else 1))
        end = rng.end()
    tail = t[found[0].start(): end + 30].lower()
    hourly = bool(re.search(r"(/\s?h(ou)?r|an hour|per hour|hourly)", tail)) or (max(nums) < 300 and not re.search(r"(year|yr|annual)", tail))
    monthly = bool(re.search(r"(/\s?mo|a month|per month|monthly)", tail))
    weekly = bool(re.search(r"(/\s?wk|a week|per week|weekly)", tail))
    mult = HOURS_PER_YEAR if hourly else 12 if monthly else 52 if weekly else 1
    nums = [round(n * mult) for n in nums]
    if max(nums) < 1000:  # a stray small figure ("$5 sign-on gift card"), not pay
        return None, None
    return min(nums), max(nums)


def posted_days(text: str, now: datetime | None = None):
    """How many days ago a posting went up, from '3 days ago', 'Posted 2 weeks ago', 'Just posted', '30+ days ago'
    or an ISO date."""
    t = (text or "").lower()
    if not t:
        return None
    if re.search(r"just posted|today|just now|moments? ago|minutes? ago|hours? ago|\bnew\b", t):
        return 0
    m = re.search(r"(\d+)\+?\s*(day|week|month|year)s?\s*ago", t) or re.search(r"(\d+)\+?\s*(d|w|mo|y)\b", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)[0] if m.group(2) != "mo" else "m"
        return n * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
    if "yesterday" in t:
        return 1
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        try:
            d = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            return max(0, ((now or datetime.now(timezone.utc)) - d).days)
        except ValueError:
            return None
    return None


def _title_match(title: str, targets: list) -> float:
    """0..1: the best overlap between the posting's title and any of the wanted titles."""
    tw = set(words(title))
    if not tw or not targets:
        return 0.0
    best = 0.0
    for target in targets:
        want = set(words(target))
        if not want:
            continue
        if " ".join(words(target)) in " ".join(words(title)):
            return 1.0
        best = max(best, len(want & tw) / len(want))
    return best


def _hit(term: str, text: str) -> bool:
    term = term.strip().lower()
    if not term:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _place_match(location: str, places: list) -> bool:
    loc = (location or "").lower()
    for p in places:
        city = p.split(",")[0].strip().lower()
        if city and city in loc:
            return True
    return False


def score(job: dict, profile: dict, now: datetime | None = None) -> dict:
    """{'score', 'verdict', 'reasons': [...], 'cautions': [...], 'level', 'remote', 'pay_min', 'pay_max', 'age_days'}"""
    title = job.get("title") or ""
    desc = job.get("description") or ""
    blob = " ".join([title, job.get("company") or "", job.get("location") or "", job.get("pay_text") or "",
                     job.get("job_type") or "", desc, " ".join(job.get("tags") or [])]).lower()
    reasons, cautions = [], []
    pts = 0.0
    no_prefs = not (profile.get("target_titles") or profile.get("skills"))

    # title (35)
    tm = _title_match(title, profile.get("target_titles") or [])
    pts += 35 * tm
    if tm >= 0.99:
        reasons.append("Title matches what you're after")
    elif tm >= 0.5:
        reasons.append("Title is close to what you're after")
    elif profile.get("target_titles"):
        cautions.append("Title isn't one of your target roles")

    # skills (25): share of your skills the posting mentions, with a card's short text judged more gently
    skills = profile.get("skills") or []
    hits = [s for s in skills if _hit(s, blob)]
    if skills:
        expect = min(len(skills), 6 if desc else 2)
        pts += 25 * min(1.0, len(hits) / expect)
        if hits:
            reasons.append("Mentions " + ", ".join(hits[:5]))

    # location and arrangement (15)
    remote = job.get("remote") or remote_of(title, job.get("location") or "", job.get("tags") and " ".join(job["tags"]) or "", desc[:1500])
    allowed = profile.get("remote") or ["remote", "hybrid", "onsite"]
    places = profile.get("locations") or []
    loc_ok = None
    if remote == "remote":
        loc_ok = "remote" in allowed
        (reasons if loc_ok else cautions).append("Remote" if loc_ok else "Remote, which you've ruled out")
    elif places and job.get("location"):
        near = _place_match(job["location"], places)
        arrangement_ok = (remote or "onsite") in allowed
        loc_ok = near and arrangement_ok
        if near and arrangement_ok:
            reasons.append(f"In {job['location']}")
        elif not near:
            cautions.append(f"{job['location']} isn't one of your locations")
        else:
            cautions.append(f"{remote.capitalize()}, which you've ruled out")
    pts += 15 if loc_ok else 7 if loc_ok is None else 0

    # pay (15)
    lo, hi = job.get("pay_min"), job.get("pay_max")
    if lo is None and hi is None:
        lo, hi = pay_of(job.get("pay_text") or "")
        if lo is None and desc:
            lo, hi = pay_of(_pay_line(desc))
    floor = profile.get("min_salary")
    if hi is not None and floor:
        if hi >= floor:
            pts += 15
            reasons.append(f"Pays up to ${hi:,}")
        elif hi >= floor * 0.9:
            pts += 7
            cautions.append(f"Pay tops out at ${hi:,}, just under your ${floor:,}")
        else:
            cautions.append(f"Pay tops out at ${hi:,}, under your ${floor:,}")
    elif hi is not None:
        pts += 12
    else:
        pts += 6
        if floor:
            cautions.append("No pay listed")

    # level (10)
    level = level_of(title)
    wanted_levels = profile.get("seniority") or []
    level_ok = not wanted_levels or level in wanted_levels or (level == "mid" and not set(wanted_levels) - {"entry", "senior"})
    pts += 10 if level_ok else 0
    if not level_ok:
        cautions.append(f"Looks {level}-level")

    # freshness and competition (5)
    age = posted_days(job.get("posted_text") or job.get("posted_at") or "", now)
    max_age = profile.get("max_age_days") or 30
    if age is None:
        pts += 3
    elif age <= 7:
        pts += 5
        reasons.append("Posted this week" if age else "Posted today")
    elif age <= max_age:
        pts += 3
    else:
        cautions.append(f"Posted {age} days ago")
    if job.get("applicants") and job["applicants"] >= 200:
        cautions.append(f"{job['applicants']}+ applicants")
        pts -= 3
    asked = (facts.years(desc) or {}).get("required")
    have = profile.get("years_experience")
    if asked and have is not None and asked > have + 1:
        cautions.append(f"Asks for {asked}+ years; your profile says {have:g}")

    pts = max(0, min(100, round(pts)))

    # hard stops
    avoided = [w for w in profile.get("avoid_keywords") or [] if _hit(w, blob)]
    if avoided:
        cautions.insert(0, "Mentions " + ", ".join(avoided) + " (on your avoid list)")
        pts = min(pts, 25)
    if loc_ok is False and remote == "remote":
        pts = min(pts, 40)
    if not level_ok and level in ("director", "executive", "intern") and "entry" in wanted_levels:
        pts = min(pts, 35)
    if not desc:
        # a search card says little about requirements, so a card alone never reads as a sure thing
        pts = min(pts, 75)
    if job.get("closed"):
        cautions.insert(0, "No longer accepting applications")
        pts = min(pts, 10)

    verdict = APPLY if pts >= 70 else CONSIDER if pts >= 50 else SKIP
    if no_prefs:
        cautions.insert(0, "Add target roles and skills on your Profile for a real score")
    return {"score": pts, "verdict": verdict, "reasons": reasons, "cautions": cautions, "level": level,
            "remote": remote, "pay_min": lo, "pay_max": hi, "age_days": age}


def _pay_line(desc: str) -> str:
    """The first stretch of a description that talks about pay, so a stray '$' elsewhere isn't read as salary."""
    m = re.search(r"(?i)(salary|pay|compensation|wage|rate)[^\n]{0,40}\$[^\n]{0,80}", desc)
    if m:
        return m.group(0)
    m = re.search(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kK]?\s?(?:-|–|to)\s?\$\s?\d[\d,]*(?:\.\d+)?\s?[kK]?[^\n]{0,30}", desc)
    return m.group(0) if m else ""

