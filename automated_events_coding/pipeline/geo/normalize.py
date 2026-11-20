"""Deterministic name normalization for place lookups.

Every lookup in the cascade is an exact match on a *key*. A name is turned into
a few keys, grouped into tiers (see key_tiers), and each key is looked up
verbatim. There are no similarity scores and no thresholds: recall comes from
these deterministic variants plus alias tables built from authoritative
sources (see build_assets.py).

The only things to curate here are the word lists below.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

# Terms the original Step 2.1 code stripped from query names. Kept for backward
# compatibility. Applied to query names only, never to dictionary entries.
EXCLUSION_TERMS = (
    "dam", "province", "water supply scheme", "river", "south",
    "earth canal", "basin", "territory",
)

# Generic words for "river" that are interchangeable between spellings of the
# same name ("Kagera", "Kagera River", "Rio Kagera"). Stripped from BOTH
# dictionary entries and queries so the variants meet at the same key.
# Deliberately excludes lake/reservoir/canal words: "Lake Victoria" and the
# "Victoria River" are different features and must not collapse together.
WATERCOURSE_TERMS = (
    "river", "rivers", "rio", "riviere", "rivier", "fleuve", "fluss",
    "nahr", "nehri", "darya", "daryo", "wadi", "oued", "rud", "nadi",
    "gol", "he", "jiang", "creek", "stream",
)

# Words that mark a dam or reservoir. Used for routing, and stripped from
# query names (as the legacy code did with "dam").
DAM_TERMS = (
    "dam", "dams", "barrage", "weir", "reservoir", "presa", "represa",
    "baraji", "hydroelectric", "hydropower", "power station", "power plant",
)

# Extra words that route a name to watercourse sources but are NOT stripped
# ("Karakum Canal" is not the same thing as "Karakum").
_WATERCOURSE_ROUTE_ONLY = ("canal", "channel")


class Route(str, Enum):
    """Which kinds of feature a name should be looked up against."""

    WATERCOURSE = "watercourse"
    DAM = "dam"
    UNKNOWN = "unknown"


def norm(s) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace. NaN-safe."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s'-]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def compact(key: str) -> str:
    """Drop spaces, hyphens, apostrophes: 'amu-darya' / 'amu darya' -> 'amudarya'."""
    return re.sub(r"[\s'_-]+", "", key)


def _phrase_pattern(terms) -> re.Pattern:
    # Whole-phrase matching, longest first, so multi-word terms such as
    # "water supply scheme" are removed as a unit. (The original word-by-word
    # filter could never remove multi-word terms.)
    alts = sorted({norm(t) for t in terms if norm(t)}, key=len, reverse=True)
    body = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"(?<![\w'-])(?:{body})(?![\w'-])")


_WATERCOURSE_STRIP = _phrase_pattern(WATERCOURSE_TERMS)
_QUERY_STRIP = _phrase_pattern(WATERCOURSE_TERMS + EXCLUSION_TERMS + DAM_TERMS)
_DAM_ROUTE = _phrase_pattern(DAM_TERMS)
_WATERCOURSE_ROUTE = _phrase_pattern(WATERCOURSE_TERMS + _WATERCOURSE_ROUTE_ONLY)


def _strip(text: str, pattern: re.Pattern) -> str:
    return re.sub(r"\s+", " ", pattern.sub(" ", text)).strip()


def search_forms(name) -> list[str]:
    """Readable (non-compacted) forms of a name, most specific first.

    Used for text search APIs, where compacted keys would not help.
    """
    full = norm(name)
    if not full:
        return []
    forms = [full, _strip(full, _WATERCOURSE_STRIP), _strip(full, _QUERY_STRIP)]
    return [f for f in dict.fromkeys(forms) if f]


def key_tiers(name, *, query: bool = False) -> list[list[str]]:
    """Exact-match keys for a name, grouped into tiers.

    Keys within a tier are equivalent: they differ only by generic river words,
    spacing or hyphenation, so lookups take the union of their hits. Tiers are
    tried in order and the first tier with any hit wins.

    Tier 1: the full name and the name without river words, each also compacted.
    Tier 2 (query=True only): the name with the legacy exclusion terms and dam
            words removed too, so the original behaviour is preserved as a fallback.
    """
    full = norm(name)
    if not full:
        return []
    stripped = _strip(full, _WATERCOURSE_STRIP)
    tiers = [[full, compact(full), stripped, compact(stripped)]]
    if query:
        legacy = _strip(full, _QUERY_STRIP)
        tiers.append([legacy, compact(legacy)])
    out: list[list[str]] = []
    seen: set[str] = set()
    for tier in tiers:
        keys = [k for k in dict.fromkeys(tier) if k and k not in seen]
        seen.update(keys)
        if keys:
            out.append(keys)
    return out


def lookup_keys(name, *, query: bool = False) -> list[str]:
    """All keys for a name, flattened (used to index names)."""
    return [k for tier in key_tiers(name, query=query) for k in tier]


def classify_route(name) -> Route:
    """Route a name by its generic words. Ambiguous or bare names search everything."""
    n = norm(name)
    is_dam = bool(_DAM_ROUTE.search(n))
    is_water = bool(_WATERCOURSE_ROUTE.search(n))
    if is_dam and not is_water:
        return Route.DAM
    if is_water and not is_dam:
        return Route.WATERCOURSE
    return Route.UNKNOWN