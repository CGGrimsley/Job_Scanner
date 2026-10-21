"""Place names for the Profile's location picker: US states, US cities of 5,000+ people and world cities of
150,000+, from GeoNames (CC BY 4.0, geonames.org) via the geonamescache package. Bundled, so it works offline."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

US_STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
             "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
             "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
             "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
             "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
             "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
             "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
             "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
             "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
STATE_CODES = {v.lower(): k for k, v in US_STATES.items()}


def fold(s: str) -> str:
    """Lower case without accents, so "san jose" finds San José."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def _places() -> list:
    rows = json.loads(Path(__file__).with_name("places.json").read_text(encoding="utf-8"))
    return [(label, pop, fold(label)) for label, pop in rows]


def search(q: str, limit: int = 10) -> list:
    """Places whose name (or any word of it) starts with what was typed, biggest first; states lead."""
    q = fold(q).strip()
    if len(q) < 2:
        return []
    word = re.compile(r"(^|[\s,(-])" + re.escape(q))
    # the sites it reads are mostly American, so US places come first, then the rest of the world; biggest first
    buckets = [[], [], [], []]  # US starts-with, world starts-with, US word match, world word match
    for label, _pop, low in _places():
        us = label in US_NAMES or bool(_US.search(label))
        if low.startswith(q):
            buckets[0 if us else 1].append(label)
        elif word.search(low):
            buckets[2 if us else 3].append(label)
        if len(buckets[0]) >= limit:
            break
    return [x for b in buckets for x in b][:limit]


US_NAMES = set(US_STATES.values())
_US = re.compile(r", [A-Z]{2}$")
