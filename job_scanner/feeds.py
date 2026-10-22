"""Job feeds that are meant to be read by programs: employers' public job boards on Greenhouse, Lever, Ashby and
SmartRecruiters, the USAJobs search API and the Adzuna search API.

Nothing here loads LinkedIn or Indeed. Their terms forbid automated access, so their jobs come in only through pages
the person browses (the extension) or the alert emails those sites send them (mail.py).

Each fetcher returns rows in the shape the extension sends (jobs.clean_row), so watched jobs merge with ones seen
while browsing: a Greenhouse posting has the same id either way.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from . import __version__

UA = f"JobScanner/{__version__} (a personal job search app running on the user's own computer)"
TIMEOUT = 20
BOARDS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters"}


class FeedError(RuntimeError):
    pass


def get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    host = urllib.parse.urlparse(url).netloc
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise FeedError(f"{host} answered {e.code}" + (" (check the key)" if e.code in (401, 403) else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FeedError(f"Couldn't reach {host}: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise FeedError(f"{host} didn't send JSON") from None


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}

    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        self.out.append(data)


def html_text(markup: str | None) -> str:
    """Plain text from a posting's HTML, keeping paragraphs and bullets."""
    p = _Text()
    p.feed(html.unescape(markup or "") if "&lt;" in (markup or "") else (markup or ""))
    text = re.sub(r"[ \t\xa0]+", " ", "".join(p.out))
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _date(v) -> str:
    """An ISO date from an ISO string or epoch milliseconds, for the posted-days reader."""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc).date().isoformat()
    return str(v or "")[:10]


def _arrangement(*texts) -> str | None:
    t = " ".join(str(x or "") for x in texts).lower()
    for k in ("hybrid", "remote", "onsite"):
        if k in t.replace("on-site", "onsite"):
            return k
    return None


# --- employers' job boards -----------------------------------------------------------------------------------

_BOARD_URLS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("lever", r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.%-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)"),
]


def board_from_url(url: str) -> tuple | None:
    """(provider, token) for a link to an employer's board, e.g. https://jobs.lever.co/acme -> ('lever', 'acme')."""
    for provider, rx in _BOARD_URLS:
        m = re.search(rx, url or "", re.I)
        if m and m.group(1).lower() not in ("embed", "jobs", "v1"):
            return provider, urllib.parse.unquote(m.group(1))
    return None


def board_url(provider: str, token: str) -> str:
    return {"greenhouse": f"https://job-boards.greenhouse.io/{token}", "lever": f"https://jobs.lever.co/{token}",
            "ashby": f"https://jobs.ashbyhq.com/{token}",
            "smartrecruiters": f"https://careers.smartrecruiters.com/{token}"}[provider]


def board_name(provider: str, token: str) -> str:
    """The employer's own name for a board where the API says it (Greenhouse); else ''."""
    if provider == "greenhouse":
        try:
            return str(get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}").get("name") or "")
        except FeedError:
            return ""
    return ""


def fetch_board(provider: str, token: str, company: str = "", want=None, details: int = 25) -> list:
    """Every open job on one employer's board. `want(row)` picks which ones are worth the full description where
    that costs another request (SmartRecruiters)."""
    t = urllib.parse.quote(token, safe="")
    company = company or token
    rows = []
    if provider == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true")
        for j in data.get("jobs") or []:
            rows.append({"source": "greenhouse", "id": str(j.get("id")), "kind": "item", "title": j.get("title"),
                         "company": j.get("company_name") or company, "location": (j.get("location") or {}).get("name"),
                         "url": j.get("absolute_url"), "description": html_text(j.get("content")),
                         "posted_text": _date(j.get("first_published") or j.get("updated_at"))})
    elif provider == "lever":
        for j in get_json(f"https://api.lever.co/v0/postings/{t}?mode=json") or []:
            cat = j.get("categories") or {}
            parts = [j.get("descriptionPlain") or html_text(j.get("description"))]
            for lst in j.get("lists") or []:
                parts.append(f"{lst.get('text', '')}\n{html_text(lst.get('content'))}")
            parts.append(j.get("additionalPlain") or "")
            sal = j.get("salaryRange") or {}
            pay = ""
            if sal.get("min") or sal.get("max"):
                per = {"per-year-salary": "a year", "per-hour-wage": "an hour", "per-month-salary": "a month"}.get(sal.get("interval"), "")
                pay = f"${sal.get('min', 0):,} - ${sal.get('max', 0):,} {per}".strip()
            rows.append({"source": "lever", "id": j.get("id"), "kind": "item", "title": j.get("text"), "company": company,
                         "location": cat.get("location") or ", ".join(cat.get("allLocations") or []), "url": j.get("hostedUrl"),
                         "description": "\n\n".join(p for p in parts if p).strip(), "job_type": cat.get("commitment"),
                         "pay_text": pay, "remote": _arrangement(j.get("workplaceType")), "posted_text": _date(j.get("createdAt"))})
    elif provider == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{t}?includeCompensation=true")
        for j in data.get("jobs") or []:
            if j.get("isListed") is False:
                continue
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            rows.append({"source": "ashby", "id": j.get("id"), "kind": "item", "title": j.get("title"), "company": company,
                         "location": j.get("location"), "url": j.get("jobUrl"), "description": j.get("descriptionPlain") or html_text(j.get("descriptionHtml")),
                         "job_type": j.get("employmentType"), "pay_text": comp, "posted_text": _date(j.get("publishedAt")),
                         "remote": "remote" if j.get("isRemote") else _arrangement(j.get("workplaceType"))})
    elif provider == "smartrecruiters":
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{t}/postings?limit=100")
        fetched = 0
        for j in data.get("content") or []:
            loc = j.get("location") or {}
            row = {"source": "smartrecruiters", "id": str(j.get("id")), "kind": "card", "title": j.get("name"),
                   "company": (j.get("company") or {}).get("name") or company,
                   "location": loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region")) if x),
                   "url": f"https://jobs.smartrecruiters.com/{t}/{j.get('id')}", "job_type": (j.get("typeOfEmployment") or {}).get("label"),
                   "remote": "remote" if loc.get("remote") else None, "posted_text": _date(j.get("releasedDate"))}
            if fetched < details and j.get("ref") and (want is None or want(row)):
                fetched += 1
                try:
                    secs = ((get_json(j["ref"]).get("jobAd") or {}).get("sections") or {})
                    row["description"] = "\n\n".join(html_text((secs.get(k) or {}).get("text")) for k in
                                                     ("companyDescription", "jobDescription", "qualifications", "additionalInformation")).strip()
                    row["kind"] = "item"
                except FeedError:
                    pass
            rows.append(row)
    else:
        raise FeedError(f"Unknown job board type: {provider}")
    return [r for r in rows if r.get("id") and r.get("title")]


# --- search APIs -----------------------------------------------------------------------------------------------


def usajobs(key: str, email: str, keyword: str, where: str = "", radius: int = 25, days: int = 14) -> list:
    """USAJobs' official search API (free key from developer.usajobs.gov; it asks for the email you registered)."""
    q = {"Keyword": keyword, "ResultsPerPage": 100, "DatePosted": days}
    if where:
        q.update({"LocationName": where, "Radius": radius})
    data = get_json("https://data.usajobs.gov/api/search?" + urllib.parse.urlencode(q),
                    {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key})
    rows = []
    for item in ((data.get("SearchResult") or {}).get("SearchResultItems") or []):
        d = item.get("MatchedObjectDescriptor") or {}
        det = ((d.get("UserArea") or {}).get("Details") or {})
        pay = (d.get("PositionRemuneration") or [{}])[0]
        per = {"PA": "a year", "PH": "an hour", "PM": "a month", "BW": "every two weeks"}.get(pay.get("RateIntervalCode"), "")
        lo, hi = pay.get("MinimumRange"), pay.get("MaximumRange")
        duties = det.get("MajorDuties") or []
        desc = "\n\n".join(x for x in [det.get("JobSummary"), "Duties:\n" + "\n".join(f"- {x}" for x in duties) if duties else "",
                                       d.get("QualificationSummary"), det.get("Education")] if x)
        rows.append({"source": "usajobs", "id": str(item.get("MatchedObjectId") or d.get("PositionID")), "kind": "item",
                     "title": d.get("PositionTitle"), "company": d.get("OrganizationName") or d.get("DepartmentName"),
                     "location": d.get("PositionLocationDisplay"), "url": d.get("PositionURI"), "description": desc,
                     "pay_text": f"${float(lo):,.0f} - ${float(hi):,.0f} {per}".strip() if lo and hi else "",
                     "job_type": ((d.get("PositionSchedule") or [{}])[0]).get("Name"), "posted_text": _date(d.get("PublicationStartDate")),
                     "remote": "remote" if str(det.get("RemoteIndicator")).lower() == "true" else None})
    return rows


def adzuna(app_id: str, app_key: str, keyword: str, where: str = "", radius: int = 25, days: int = 14) -> list:
    """Adzuna's search API (free key from developer.adzuna.com). It only gives a snippet of each description, so
    these come in as cards: open one and the extension reads the full posting. Salaries Adzuna estimated itself
    (salary_is_predicted) are left out."""
    q = {"app_id": app_id, "app_key": app_key, "what": keyword, "results_per_page": 50, "max_days_old": days,
         "content-type": "application/json"}
    if where:
        q.update({"where": where, "distance": round(radius * 1.609)})
    data = get_json("https://api.adzuna.com/v1/api/jobs/us/search/1?" + urllib.parse.urlencode(q))
    rows = []
    for j in data.get("results") or []:
        real_pay = str(j.get("salary_is_predicted")) != "1" and j.get("salary_min")
        rows.append({"source": "adzuna", "id": str(j.get("id")), "kind": "card", "title": html_text(j.get("title")),
                     "company": (j.get("company") or {}).get("display_name"), "location": (j.get("location") or {}).get("display_name"),
                     "url": j.get("redirect_url"), "posted_text": _date(j.get("created")),
                     "job_type": {"full_time": "Full-time", "part_time": "Part-time"}.get(j.get("contract_time"), ""),
                     "pay_min": int(j["salary_min"]) if real_pay else None, "pay_max": int(j.get("salary_max") or j["salary_min"]) if real_pay else None,
                     "_snippet": html_text(j.get("description"))})
    return rows
