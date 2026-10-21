"""The tracker's to-do list: when to apply, reach out, follow up, say thank you, or let a job go.

Plain rules on the dates the person records, no AI. The timings follow common recruiting advice: apply within a
week or so of a posting going up, reach out to someone at the company when you apply, follow up about a week after
applying and once more a week later, send a thank-you within a day of an interview, and stop waiting after about a
month of silence. Claude can draft the message for any of them (ai.draft_message)."""

from __future__ import annotations

from datetime import date

from . import scoring

ACTIVE = ("saved", "applied", "interviewing", "offer")


def _days(since: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(since)[:10])).days
    except ValueError:
        return None


def nudges(rec: dict, today: date | None = None) -> list:
    """[{'id', 'urgency': 'now'|'soon'|'info', 'title', 'why', 'message': kind of message Claude can draft or None}]"""
    today = today or date.today()
    st = rec.get("status") or ""
    done = set(rec.get("done") or [])
    out = []

    def add(nid, urgency, title, why, message=None):
        if nid not in done:
            out.append({"id": nid, "urgency": urgency, "title": title, "why": why, "message": message})

    if rec.get("follow_up") and st in ACTIVE:
        d = _days(rec["follow_up"], today)
        if d is not None and d >= 0:
            add(f"reminder-{rec['follow_up']}", "now", "Your follow-up date is here",
                f"You set a reminder for {rec['follow_up']}.", "follow_up")

    if st == "saved":
        age = scoring.posted_days(rec.get("posted_text") or "", None)
        saved = _days(next((h["at"] for h in reversed(rec.get("history", [])) if h.get("status") == "saved"), ""), today)
        if rec.get("closed"):
            add("closed", "now", "This posting has closed", "The site says it's no longer taking applications. Let it go.")
        elif (age is not None and age >= 14) or (saved is not None and saved >= 5):
            add("apply-soon", "now", "Apply soon or let it go",
                "Applications sent in the first week or two get the most attention; this one has been waiting a while.")
        else:
            add("apply", "soon", "Apply while it's fresh", "Early applications are seen first.")
        if rec.get("ai") and rec["ai"].get("verdict") == "Skip":
            add("weak-fit", "info", "Claude rated this a weak fit",
                "Check Claude's gaps before spending time on an application.")

    if st == "applied":
        d = _days(rec.get("applied_at") or "", today)
        if not rec.get("contact"):
            add("reach-out", "soon", "Reach out to someone there",
                "A short note to the recruiter or hiring manager (LinkedIn works) makes it more likely your application is read. "
                "Add their name under Contact once you have it.", "networking")
        if d is not None:
            if 7 <= d < 14:
                add("follow-up-1", "now", "Send a follow-up", f"You applied {d} days ago with no update. A brief, polite check-in is normal now.", "follow_up")
            elif 14 <= d < 30:
                add("follow-up-2", "now", "One last follow-up", f"It's been {d} days. One more short note, then move on if there's no answer.", "follow_up")
            elif d >= 30:
                add("stale", "info", "Probably time to move on",
                    f"{d} days without a reply usually means it isn't moving. Mark it Rejected or Withdrawn to clear it, or keep waiting if you've heard otherwise.")

    if st == "interviewing":
        d = _days(rec.get("interview_at") or "", today)
        if not rec.get("interview_at"):
            add("interview-date", "info", "Add your interview date", "Then you'll get a reminder to send a thank-you note and to follow up.")
        elif d is not None and d < 0:
            add(f"prep-{rec['interview_at']}", "soon", f"Interview in {-d} day{'s' if d != -1 else ''}",
                "Re-read the posting and Claude's gaps and questions to ask; have an honest answer ready for each gap.")
        elif d is not None and d <= 1:
            add(f"thanks-{rec['interview_at']}", "now", "Send a thank-you note today", "Within a day of the interview is best.", "thank_you")
        elif d is not None and d >= 7:
            add(f"after-interview-{rec['interview_at']}", "now", "Follow up on your interview",
                f"It's been {d} days since your interview. Ask politely about the timeline.", "follow_up")

    if st == "offer":
        add("offer", "now", "Respond to the offer",
            "Ask for it in writing, check it against your minimum pay and dealbreakers, and negotiate if it's under the market rate.",
            "offer_reply")
    return out


def todo(recs: list, today: date | None = None) -> list:
    """Every tracked job's to-dos, most urgent first."""
    rank = {"now": 0, "soon": 1, "info": 2}
    out = []
    for r in recs:
        for n in nudges(r, today):
            out.append({**n, "key": r["key"], "title_job": r.get("title"), "company": r.get("company")})
    out.sort(key=lambda n: rank[n["urgency"]])
    return out
