"""Search links you open yourself: a role and a place, tuned to surface the postings worth seeing (newest first,
the last day or week, the arrangement you want), with your avoid-list words left out. The app never fetches these
sites; the extension reads the results as you scroll, like any other search."""

from __future__ import annotations

from urllib.parse import urlencode

LINKEDIN_WT = {"remote": "2", "hybrid": "3", "onsite": "1"}


def _query(title: str, avoid: list, style: str) -> str:
    t = f'"{title}"' if " " in title else title
    words = [w for w in avoid if w and len(w) < 40][:5]
    if style == "linkedin":
        return " ".join([t] + [f'NOT "{w}"' if " " in w else f"NOT {w}" for w in words])
    if style == "indeed":
        return " ".join([t] + [f'-"{w}"' if " " in w else f"-{w}" for w in words])
    return title


def links(title: str, place: str = "", remote: list | None = None, avoid: list | None = None) -> list:
    """[{'site', 'label', 'url'}] for one role in one place."""
    remote, avoid = remote or [], avoid or []
    only_remote = remote == ["remote"]
    out = []
    li = {"keywords": _query(title, avoid, "linkedin"), "location": "United States" if only_remote or not place else place,
          "sortBy": "DD"}
    if remote and set(remote) != {"remote", "hybrid", "onsite"}:
        li["f_WT"] = ",".join(LINKEDIN_WT[r] for r in remote if r in LINKEDIN_WT)
    if place and not only_remote:
        li["distance"] = "25"
    out.append({"site": "LinkedIn", "label": "Past 24 hours", "url": "https://www.linkedin.com/jobs/search/?" + urlencode({**li, "f_TPR": "r86400"})})
    out.append({"site": "LinkedIn", "label": "Past week", "url": "https://www.linkedin.com/jobs/search/?" + urlencode({**li, "f_TPR": "r604800"})})
    ind = {"q": _query(title, avoid, "indeed"), "l": "Remote" if only_remote else place, "sort": "date"}
    if place and not only_remote:
        ind["radius"] = "25"
    out.append({"site": "Indeed", "label": "Past day", "url": "https://www.indeed.com/jobs?" + urlencode({**ind, "fromage": "1"})})
    out.append({"site": "Indeed", "label": "Past week", "url": "https://www.indeed.com/jobs?" + urlencode({**ind, "fromage": "7"})})
    out.append({"site": "USAJobs", "label": "Government jobs", "url": "https://www.usajobs.gov/search/results/?" + urlencode({"k": title, "l": "" if only_remote else place})})
    out.append({"site": "Google", "label": "Jobs from every board", "url": "https://www.google.com/search?" + urlencode({"q": f"{title} jobs {place}".strip(), "ibp": "htl;jobs"})})
    return out


def for_profile(p: dict, extra_titles: list | None = None, limit: int = 8) -> list:
    """[{'title', 'place', 'links'}] for your target roles (and suggested ones) in each place you've chosen."""
    titles = list(dict.fromkeys((p.get("target_titles") or []) + list(extra_titles or [])))[:limit]
    places = (p.get("locations") or [""])[:3]
    if p.get("remote") == ["remote"]:
        places = [""]
    return [{"title": t, "place": pl, "links": links(t, pl, p.get("remote") or [], p.get("avoid_keywords") or [])}
            for t in titles for pl in places]
