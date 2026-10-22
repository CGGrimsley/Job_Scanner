"""LinkedIn and Indeed job alert emails, read from the person's own mailbox. This is how jobs from those two sites can
come in without anyone browsing: the sites email new matches for a saved search, and the app reads those emails.
It never loads LinkedIn or Indeed itself.

The mailbox is opened read-only over IMAP (messages aren't marked as read or changed) with the address and an app
password the person enters in Setup. Each alert becomes a card under the same id the extension uses, so opening
it in the browser fills in the full posting.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import policy
from html.parser import HTMLParser

SENDERS = {"linkedin": "linkedin.com", "indeed": "indeed.com"}
LINKEDIN_ID = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?\"]*-)?(\d{6,})")
INDEED_ID = re.compile(r"[?&](?:jk|vjk)=([0-9a-f]{10,20})", re.I)
SKIP_TEXT = re.compile(r"^(view job|see all jobs|see more jobs|apply now|easy apply|unsubscribe|search for jobs|view all|manage|"
                       r"settings|help|privacy|learn more|.*\bjobs? (?:for|like) you\b.*|new jobs?.*)$", re.I)


class MailError(RuntimeError):
    pass


class _Links(HTMLParser):
    """The email's text in order, with each link's address and words, so a job link can be read together with the
    company and place written right after it."""

    def __init__(self):
        super().__init__()
        self.items, self.href, self.buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._flush()
            self.href = dict(attrs).get("href") or ""
        elif tag in ("br", "p", "div", "td", "tr", "li", "table", "h1", "h2", "h3", "h4"):
            self._flush()

    def handle_endtag(self, tag):
        if tag == "a":
            self._flush()
            self.href = None
        elif tag in ("p", "div", "td", "tr", "li", "h1", "h2", "h3", "h4"):
            self._flush()

    def handle_data(self, data):
        self.buf.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.items.append((text, self.href))


def parse_alert(markup: str, site: str) -> list:
    """Job cards from one alert email's HTML."""
    p = _Links()
    p.feed(markup or "")
    items, rows, seen = p.items, [], set()
    for i, (text, href) in enumerate(items):
        if not href or SKIP_TEXT.match(text) or len(text) < 4 or len(text) > 150:
            continue
        if site == "linkedin":
            m = LINKEDIN_ID.search(href)
            jid = m and m.group(1)
            url = f"https://www.linkedin.com/jobs/view/{jid}/" if jid else None
        else:
            if "indeed." not in href and "indeed" not in href:
                continue
            m = INDEED_ID.search(href)
            jid = m.group(1) if m else None
            url = f"https://www.indeed.com/viewjob?jk={jid}" if jid else href
        if site == "linkedin" and not jid:
            continue
        # what follows the title, up to the next link: "Company · Place", or company then place
        after = []
        for t, h in items[i + 1:i + 6]:
            if h and (LINKEDIN_ID.search(h) or INDEED_ID.search(h) or "indeed" in h):
                if after or t == text:
                    break
                continue
            if not SKIP_TEXT.match(t):
                after.append(t)
            if len(after) >= 3:
                break
        parts = [x.strip() for x in re.split(r"\s+[·•|-]\s+", after[0])] if after else []
        company = parts[0] if parts else ""
        place = parts[1] if len(parts) > 1 else (after[1] if len(after) > 1 else "")
        if not company or company == text:
            continue
        if not jid:  # Indeed sometimes wraps every link; then the job is known by its title and employer
            jid = "m" + hashlib.sha1(f"{text}|{company}".lower().encode()).hexdigest()[:15]
        if jid in seen:
            continue
        seen.add(jid)
        pay = next((t for t in after if "$" in t), "")
        rows.append({"source": site, "id": jid, "kind": "card", "title": text, "company": company,
                     "location": place if "$" not in place else "", "url": url, "pay_text": pay})
    return rows


def _html_of(msg) -> str:
    part = msg.get_body(preferencelist=("html",))
    return part.get_content() if part else ""


def fetch_alerts(cfg: dict, since: datetime | None = None, done: set | None = None) -> tuple:
    """(rows, message ids read) from LinkedIn and Indeed alerts in the mailbox since `since`, skipping ids in `done`."""
    since = since or datetime.now(timezone.utc) - timedelta(days=14)
    done = done or set()
    try:
        box = imaplib.IMAP4_SSL(cfg["host"], int(cfg.get("port") or 993), timeout=30)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError(f"Couldn't connect to {cfg.get('host')}: {e}") from None
    rows, read = [], []
    try:
        try:
            box.login(cfg["user"], cfg["password"])
        except imaplib.IMAP4.error:
            raise MailError("The mail server refused the login. Use an app password (Gmail, Yahoo and iCloud need one), "
                            "not your normal password.") from None
        status, _ = box.select(f'"{cfg.get("folder") or "INBOX"}"', readonly=True)
        if status != "OK":
            raise MailError(f"No folder called {cfg.get('folder') or 'INBOX'}.")
        day = since.strftime("%d-%b-%Y")
        for site, domain in SENDERS.items():
            status, data = box.search(None, "SINCE", day, "FROM", domain)
            if status != "OK":
                continue
            for num in (data[0] or b"").split()[-60:]:
                status, got = box.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not got or not isinstance(got[0], tuple):
                    continue
                msg = email.message_from_bytes(got[0][1], policy=policy.default)
                mid = str(msg.get("Message-ID") or num.decode())
                if mid in done:
                    continue
                read.append(mid)
                rows += parse_alert(_html_of(msg), site)
    finally:
        try:
            box.logout()
        except (OSError, imaplib.IMAP4.error):
            pass
    return rows, read


def test_login(cfg: dict) -> str:
    """'' when the mailbox opens, else what went wrong."""
    try:
        fetch_alerts(cfg, since=datetime.now(timezone.utc), done=set())
        return ""
    except MailError as e:
        return str(e)
