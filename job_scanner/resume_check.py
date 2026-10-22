"""A check of each résumé against what applicant tracking systems need and what your target jobs ask for. Plain
rules, no AI: things a parser trips on, and the keywords your jobs keep using that a résumé never mentions."""

from __future__ import annotations

import re

SECTIONS = {
    "experience": r"(work |professional |relevant )?(experience|employment|work history)",
    "education": r"education|degrees?|academic",
    "skills": r"(technical |core )?(skills|competencies|proficiencies)",
}
DATE = r"\b(19|20)\d{2}\b"


def check(resume: dict, missing_keywords: list | None = None) -> dict:
    """{'name', 'score', 'good': [...], 'fix': [...], 'keywords': [...]} for one résumé ({'name', 'text'})."""
    text = resume.get("text") or ""
    low = text.lower()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    words = len(re.findall(r"\w+", text))
    good, fix = [], []

    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        good.append("Has an email address")
    else:
        fix.append("Add an email address near the top: most application systems look for one")
    if re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text):
        good.append("Has a phone number")
    else:
        fix.append("Add a phone number")
    for name, rx in SECTIONS.items():
        if any(re.fullmatch(r"[#*\s]*(" + rx + r")[:\s]*", l, re.I) for l in lines):
            good.append(f"Has a clear {name.title()} heading")
        else:
            fix.append(f"Use a plain \"{name.title()}\" heading so parsers find that section")
    dates = len(re.findall(DATE, text))
    if dates >= 2:
        good.append("Jobs have dates")
    else:
        fix.append("Put dates (month and year) on each job: parsers and recruiters both look for them")
    if words < 200:
        fix.append(f"It's short ({words} words). Most résumés that get read fully run 400 to 800 words")
    elif words > 1100:
        fix.append(f"It's long ({words} words). Two pages (about 1,000 words) is the usual limit")
    else:
        good.append(f"A readable length ({words} words)")
    bullets = sum(1 for l in lines if re.match(r"^[-•*▪◦·]\s", l))
    if bullets >= 5:
        good.append("Uses bullet points")
    else:
        fix.append("Break job descriptions into bullet points, one achievement each")
    numbers = len(re.findall(r"\b\d+(\.\d+)?\s?(%|percent|k\b|\+)|\$\s?\d", text))
    if numbers >= 2:
        good.append("Shows results with numbers")
    else:
        fix.append("Where it's true, add numbers (how many, how much, how often): they make results concrete")
    if re.search(r"\b(references available|objective:)", low):
        fix.append("Drop \"Objective\" and \"References available\" lines; a short summary works better")

    kw = [m for m in (missing_keywords or []) if m.get("jobs", 0) >= 2][:12]
    total = len(good) + len(fix)
    return {"name": resume.get("name") or "Résumé", "score": round(100 * len(good) / total) if total else 0,
            "good": good, "fix": fix, "keywords": kw}


def check_all(profile: dict, missing_keywords: list | None = None) -> list:
    return [check(r, missing_keywords) for r in profile.get("resumes") or []]
