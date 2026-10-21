"""Facts read straight from a posting's text, with no AI: the years of experience it asks for, the degree, and any
security clearance. They're used to filter and sort the job list. Each is None when the posting doesn't say, which
is different from saying "none needed": a filter lets those through, since nothing rules them out.

Only requirements count. A line that calls something preferred, a plus or nice to have is kept apart, so
"Master's preferred" doesn't hide a job from someone filtering for "no degree needed"."""

from __future__ import annotations

import re

DEGREES = ("high_school", "associate", "bachelor", "master", "doctorate")
DEGREE_LABEL = {"high_school": "High school", "associate": "Associate's", "bachelor": "Bachelor's", "master": "Master's",
                "doctorate": "Doctorate"}
_DEGREE_RX = [
    ("doctorate", r"\b(ph\.?\s?d|doctorate|doctoral)\b"),
    ("master", r"\b(master'?s|masters|mba|m\.s\.|master of)\b"),
    ("bachelor", r"\b(bachelor'?s|bachelors|b\.s\.|b\.a\.|bs/ba|ba/bs|(?:bs|ba) (?:degree|in)|bachelor of|"
                 r"(?:4|four)[- ]year (?:college )?degree|undergraduate degree|college degree|university degree)\b"),
    ("associate", r"\b(associate'?s degree|associate degree|associates degree|a\.a\.s?\.|(?:2|two)[- ]year degree)\b"),
    ("high_school", r"\b(high school|ged|hsd|secondary school)\b"),
]
_PREFERRED = re.compile(r"\b(preferred|preferably|a plus|nice to have|desired|desirable|bonus|ideally|advantageous|helpful)\b", re.I)
_EQUIV = re.compile(r"\b(or equivalent|equivalent (?:combination|work|professional|practical)|or (?:related|relevant) "
                    r"(?:work )?experience|in lieu of|or comparable experience)\b", re.I)
_YEARS = re.compile(r"(\d{1,2})\)?(?:\s*(?:-|–|to)\s*\d{1,2})?\s*\+?\s*(?:plus\s+)?(?:years?|yrs?)\b(?!\s*(?:old|of age))", re.I)
_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
_EXPERIENCE = re.compile(r"\bexperience|\bexp\b|\bworking (?:in|with)\b|\bbackground in\b", re.I)

CLEARANCES = ("clearance", "public_trust", "secret", "top_secret", "ts_sci")
CLEARANCE_LABEL = {"clearance": "Security clearance", "public_trust": "Public Trust", "secret": "Secret clearance",
                   "top_secret": "Top Secret clearance", "ts_sci": "TS/SCI clearance"}
_CLEAR_RX = [
    ("ts_sci", r"\bts\s*/\s*sci\b|\btop secret\s*/\s*sci\b|\bsci eligib"),
    ("top_secret", r"\btop[- ]secret\b"),
    ("secret", r"\bsecret\b(?=[^.\n]{0,40}\bclearance\b)|\b(?:active|current|interim|dod|final)\s+secret\b|\bsecret\s+(?:level|security)\b"),
    ("public_trust", r"\bpublic trust\b"),
    ("clearance", r"\bsecurity clearance\b|\bclearance (?:is )?required\b|\bclearable\b|\bactive clearance\b"),
]
_OBTAIN = re.compile(r"\b(?:ability|able|eligib\w*|willing(?:ness)?)\s+to\s+(?:obtain|get|acquire)|\bobtain and maintain\b|"
                     r"\bclearable\b|\beligible (?:for|to)\b|\bmust be able to obtain\b", re.I)
_NO_CLEARANCE = re.compile(r"\bno (?:security )?clearance\b|\bclearance (?:is )?not required\b", re.I)


def sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+|\s[•·▪]\s", text or "") if s.strip()]


def years(text: str) -> dict | None:
    """{'required': N or None, 'preferred': N or None}: the most experience any one requirement asks for, taking
    the low end of a range ('3-5 years' is 3)."""
    req, pref = None, None
    for s in sentences(text):
        s = re.sub(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b(?=\s*(?:\(\d+\)\s*)?\+?\s*(?:years?|yrs?)\b)",
                   lambda m: str(_WORDS.index(m.group(1).lower()) + 1), s, flags=re.I)
        if not _EXPERIENCE.search(s):
            continue
        found = [int(m.group(1)) for m in _YEARS.finditer(s) if 0 < int(m.group(1)) <= 30]
        if not found:
            continue
        n = max(found)
        if _PREFERRED.search(s):
            pref = max(pref or 0, n)
        else:
            req = max(req or 0, n)
    return {"required": req, "preferred": pref} if req or pref else None


def degree(text: str) -> dict | None:
    """{'level', 'required', 'equivalent_ok'}: the lowest degree the posting accepts as a requirement (a line
    saying 'Bachelor's or Master's' needs a bachelor's), or the preferred one when it only prefers one."""
    req, pref, equiv = None, None, False
    for s in sentences(text):
        low = s.lower()
        levels = [i for i, (_, rx) in enumerate(_DEGREE_RX[::-1]) if re.search(rx, low)]
        if not levels:
            continue
        if _EQUIV.search(s):
            equiv = True
        lvl = min(levels)
        if _PREFERRED.search(s):
            pref = lvl if pref is None else min(pref, lvl)
        else:
            req = lvl if req is None else min(req, lvl)
    if req is None and pref is None:
        return None
    return {"level": DEGREES[req if req is not None else pref], "required": req is not None, "equivalent_ok": equiv}


def clearance(text: str) -> dict | None:
    """{'level', 'must_hold'}: the highest clearance mentioned, and whether you must already hold it (as opposed
    to being able to get one after you're hired)."""
    if not text or _NO_CLEARANCE.search(text):
        return None
    low = text.lower()
    for level, rx in _CLEAR_RX:
        if re.search(rx, low):
            return {"level": level, "must_hold": not _OBTAIN.search(text)}
    return None


def of(rec: dict) -> dict:
    text = "\n".join(str(rec.get(k) or "") for k in ("title", "description")) + "\n" + "\n".join(rec.get("tags") or [])
    return {"years": years(text), "degree": degree(text), "clearance": clearance(text)}


def degree_ok(d: dict | None, most: str) -> bool:
    """Whether someone with at most `most` meets the degree requirement (or the posting accepts experience instead)."""
    if not d or not d.get("required") or d.get("equivalent_ok"):
        return True
    return DEGREES.index(d["level"]) <= DEGREES.index(most)


def labels(f: dict) -> list:
    """Short tags for the list and the extension's panel, e.g. ['3+ yrs', "Bachelor's or equivalent"]."""
    out = []
    y = (f or {}).get("years")
    if y and y.get("required"):
        out.append(f"{y['required']}+ yrs")
    elif y and y.get("preferred"):
        out.append(f"{y['preferred']}+ yrs preferred")
    d = (f or {}).get("degree")
    if d:
        out.append(DEGREE_LABEL[d["level"]] + (" or equivalent" if d["equivalent_ok"] else "" if d["required"] else " preferred"))
    c = (f or {}).get("clearance")
    if c:
        out.append(CLEARANCE_LABEL[c["level"]] + ("" if c["must_hold"] else " (can obtain)"))
    return out
