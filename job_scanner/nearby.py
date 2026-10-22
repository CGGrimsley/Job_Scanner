"""Employers near the person, and where each one posts its jobs: a list of career boards worth checking.

Claude suggests the prominent employers around the profile's locations that hire for the roles they want, from its
general knowledge (no browsing, so it can be out of date). Every suggestion is then checked from this computer:
- a job board Claude names on Greenhouse, Lever, Ashby or SmartRecruiters is opened through that site's public API,
  and if it answers it can be watched automatically;
- for the others, likely board names are tried the same way. A board found by guessing could belong to a different
  employer with the same name, so it's marked for the person to check before watching;
- the careers page link is opened to see that it exists.
Employers whose boards have no public feed (Workday, iCims, Taleo, their own sites) stay in the list as links to
open: the extension reads those pages as the person browses them.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import ai, feeds

KNOWN_BOARDS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday", "icims", "taleo", "successfactors",
                "oracle", "own site", "unknown"]
SCHEMA = {"type": "object", "properties": {"employers": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"},
    "industry": {"type": "string"},
    "why": {"type": "string", "description": "One short line: why this employer is worth checking for these roles."},
    "careers_url": {"type": "string", "description": "The careers page, or '' if you aren't sure of it."},
    "board": {"type": "string", "enum": KNOWN_BOARDS},
    "board_token": {"type": "string", "description": "The board's name in its URL on Greenhouse, Lever, Ashby or SmartRecruiters, or ''."},
    "size": {"type": "string", "enum": ["large", "mid-size", "small"]}},
    "required": ["name", "industry", "why", "careers_url", "board", "board_token", "size"], "additionalProperties": False}}},
    "required": ["employers"], "additionalProperties": False}


def suggest(places: list, titles: list, skills: list, limit: int = 25) -> list:
    prompt = (f"List up to {limit} prominent employers with a real presence within about 30 miles of: {'; '.join(places)}. "
              f"The person is looking for roles like: {'; '.join(titles) or 'not given'}"
              + (f" (skills: {', '.join(skills[:12])})" if skills else "") + ".\n"
              "Include the big local employers (hospitals and health systems, universities, local and state government, "
              "major companies) and notable mid-size ones, favouring those that hire for these roles. For each, give its "
              "careers page and the job board it uses (Greenhouse, Lever, Ashby, SmartRecruiters, Workday and so on) with "
              "the board's name in its URL. Only give a URL or board you're confident of; otherwise use '' and 'unknown'. "
              "Don't invent employers or locations.")
    out = ai.ask_json("You know regional labour markets and employers well, and you say when you aren't sure.",
                      prompt, SCHEMA, kind="nearby")
    seen, items = set(), []
    for e in out.get("employers") or []:
        name = str(e.get("name") or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            items.append({k: str(e.get(k) or "").strip() for k in ("name", "industry", "why", "careers_url", "board", "board_token", "size")})
    return items[:limit]


def _slugs(name: str) -> list:
    base = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co|the|group|holdings)\b\.?", "", name.lower())
    words = re.findall(r"[a-z0-9]+", base)
    return list(dict.fromkeys(s for s in ("".join(words), "-".join(words)) if len(s) > 2))


def probe(provider: str, token: str) -> int | None:
    """How many jobs a board has open, or None if there's no such board."""
    try:
        return len(feeds.fetch_board(provider, token, details=0))
    except feeds.FeedError:
        return None


def link_ok(url: str) -> bool | None:
    if not re.match(r"https?://", url or ""):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": feeds.UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code in (401, 403, 405, 429)  # there, but turning programs away
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def check(item: dict) -> dict:
    """Fill in what this computer could confirm: `watchable` (provider, token, jobs, guessed) and `link_ok`."""
    out = dict(item)
    out["link_ok"] = link_ok(item.get("careers_url"))
    named = item.get("board") in feeds.BOARDS and item.get("board_token")
    if named:
        n = probe(item["board"], item["board_token"])
        if n is not None:
            out["watchable"] = {"provider": item["board"], "token": item["board_token"], "jobs": n, "guessed": False}
            return out
    if not named and item.get("board") in ("workday", "icims", "taleo", "successfactors", "oracle"):
        return out  # a board with no public feed: a link to open
    url_board = feeds.board_from_url(item.get("careers_url") or "")
    if url_board:
        n = probe(*url_board)
        if n is not None:
            out["watchable"] = {"provider": url_board[0], "token": url_board[1], "jobs": n, "guessed": False}
            return out
    for slug in _slugs(item["name"]):
        for provider in ("greenhouse", "lever", "ashby"):
            n = probe(provider, slug)
            if n:  # an empty board under a guessed name is more likely someone else's
                out["watchable"] = {"provider": provider, "token": slug, "jobs": n, "guessed": True}
                return out
    return out


def find(places: list, titles: list, skills: list) -> list:
    items = suggest(places, titles, skills)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(check, items))
