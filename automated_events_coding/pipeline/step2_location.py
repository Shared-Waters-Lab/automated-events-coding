"""Step 2 - Location Extraction (LLM) + 2.1/2.2 gazetteer lookups (rule-based).

Step 2
  Input: single Event
  Output: place_names: string[]
  Downstream: feeds Steps 2.1 and 2.2

Step 2.1 - Country / Basin Lookup (rule-based)
  Input: place_names
  Output: bcode (TFDD basin code) + ccodes (country codes) -- see schemas.CountryBasinLookup
  Condition: runs unconditionally

Step 2.2 - Aquifer Lookup (rule-based)
  Input: place_names
  Output: aquifer_name -- see schemas.AquiferLookup
  Condition: only runs if groundwater (GW) mentioned = Y, per the diagram --
    but per the codebook, Aquifer Name is only meaningful when Step 2.1's
    bcode == "GRND". This module currently follows the diagram (gates on
    PlaceNames.gw_mentioned in the orchestrator); see the open question in
    docs/pr-data-pipeline-spec.md.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, TypedDict
from pathlib import Path

import pandas as pd
from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, PlaceNames

logger = logging.getLogger(__name__)

# Gazetteer backing Step 2.1 (TFDD basin dictionary). Note: this file does NOT
# cover aquifers -- Step 2.2 still needs its own lookup data.
_GAZETTEER_PATH = Path(__file__).resolve().parent.parent / "static" / "Dictionaries_20260803.xlsx"
_BASIN_SHEET = "Basin Names LU"
_COUNTRY_SHEET = "Country Names LU"

# Codebook special bcode values (see schemas.CountryBasinLookup).
BCODE_UNKN = "UNKN"  # basin not identifiable from the place names
BCODE_GNRL = "GNRL"  # no place names provided at all

# need a list of terms to exclude when doing the look up
EXCLUSION_TERMS = ["dam", "province", "water supply scheme", "river", "south", "earth canal", "basin", "territory"]

class PlaceName(TypedDict):
    placename: str
    placename_type: Literal["country", "non-country"]

COUNTRY_ALIASES: dict[str, str] = {
    "russia": "russian federation",
    # ...add as i find them
}

def _norm(s) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace. NaN-safe."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s'-]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()

def _split_cell(cell) -> list[str]:
    """Split a '; '-separated cell tolerantly; drop empties and NaN."""
    if not isinstance(cell, str):
        return []
    return [n for n in (_norm(part) for part in cell.split(";")) if n]

def _canonical_country(name: str) -> str:
    n = _norm(name)
    return COUNTRY_ALIASES.get(n, n)

_EXCLUSION_NORM = frozenset(_norm(t) for t in EXCLUSION_TERMS)

def _trib_candidates(name: str) -> list[str]:
    """Try the full name first, then the name with generic terms removed."""
    full = _norm(name)
    stripped = " ".join(w for w in full.split() if w not in _EXCLUSION_NORM)
    return [c for c in dict.fromkeys((full, stripped)) if c]

@dataclass(frozen=True)
class _GazetteerIndex:
    country_to_basins: dict[str, frozenset]
    trib_to_basins: dict[str, frozenset]
    basin_countries: dict[str, tuple[str, ...]]
    country_codes: dict[str, str]

@lru_cache(maxsize=None)
def _load_gazetteer() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the basin gazetteer once.   
    """
    basins = pd.read_excel(_GAZETTEER_PATH, sheet_name=_BASIN_SHEET, engine="openpyxl")
    countries = pd.read_excel(
        _GAZETTEER_PATH, sheet_name=_COUNTRY_SHEET, engine="openpyxl"
    )

    basins["trib_bname"] = basins["Basin Name"] + "; " + basins["Tributary List"] 
    return basins, countries

@lru_cache(maxsize=1)
def _build_index() -> _GazetteerIndex:
    """Build lookup tables once. Call _build_index.cache_clear() if the sheet changes."""
    basins, countries = _load_gazetteer()

    country_to_basins = defaultdict(set)
    trib_to_basins = defaultdict(set)
    basin_countries = defaultdict(set)

    for bcode, rip, tribs in zip(
        basins["BCODE"], basins["Riparian Countries"], basins["trib_bname"]
    ):
        if pd.isna(bcode):
            continue
        for c in _split_cell(rip):
            c = COUNTRY_ALIASES.get(c, c)
            country_to_basins[c].add(bcode)
            basin_countries[bcode].add(c)
        for t in _split_cell(tribs):
            trib_to_basins[t].add(bcode)

    country_codes: dict[str, str] = {}
    for name, code in zip(countries["Country Name"], countries["CCODE"]):
        n = _canonical_country(name)
        if n and pd.notna(code):
            country_codes.setdefault(n, code)

    return _GazetteerIndex(
        country_to_basins={k: frozenset(v) for k, v in country_to_basins.items()},
        trib_to_basins={k: frozenset(v) for k, v in trib_to_basins.items()},
        basin_countries={k: tuple(sorted(v)) for k, v in basin_countries.items()},
        country_codes=country_codes,
    )

def _ccodes_for(bcode, idx: _GazetteerIndex) -> list[str]:
    codes = []
    for c in idx.basin_countries.get(bcode, ()):
        code = idx.country_codes.get(c)
        if code is None:
            logger.warning("No CCODE for riparian country %r (basin %s)", c, bcode)
            continue
        codes.append(code)
    return codes

def lookup_country_basin(place_names: list[PlaceName]) -> list[CountryBasinLookup]:
    """Step 2.1 -- resolve place names to a TFDD basin code (rule-based).

    Scoring:
      * Country mentions vote for every basin that country is riparian to.
      * Non-country mentions vote for basins listing them in trib_bname.
      * If tributary matches exist, they decide, weighted by country votes
        when the two agree; otherwise country votes alone decide.
    Ties return multiple results, sorted by bcode for determinism.

    TODO: should check if this is a useable event.
    """
    unknown = [CountryBasinLookup(bcode=BCODE_UNKN, ccodes=[])]
    if not place_names:
        return unknown

    idx = _build_index()
    country_votes: Counter = Counter()
    trib_votes: Counter = Counter()
    seen_countries: set[str] = set()
    seen_tribs: set[str] = set()

    for p in place_names:
        raw = p.get("placename") if isinstance(p, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            continue
        ptype = p.get("placename_type")

        if ptype == "country":
            c = _canonical_country(raw)
            if c in seen_countries:
                continue
            seen_countries.add(c)
            matched = idx.country_to_basins.get(c)
            if matched:
                country_votes.update(matched)
            else:
                logger.debug("Country %r not riparian to any basin", raw)

        elif ptype == "non-country":
            for cand in _trib_candidates(raw):
                matched = idx.trib_to_basins.get(cand)
                if matched:
                    if cand not in seen_tribs:
                        seen_tribs.add(cand)
                        trib_votes.update(matched)
                    break

        else:
            logger.warning("Unknown placename_type %r for %r", ptype, raw)

    if trib_votes:
        agreeing = {b: trib_votes[b] * country_votes[b] for b in trib_votes if country_votes[b]}
        # If the tributary matches contradict the countries (or there are no
        # countries), trust the tributary matches on their own.
        scores = agreeing or dict(trib_votes)
    else:
        scores = dict(country_votes)

    if not scores:
        return unknown

    best = max(scores.values())
    winners = sorted(b for b, s in scores.items() if s == best)
    return [CountryBasinLookup(bcode=b, ccodes=_ccodes_for(b, idx)) for b in winners]


def lookup_aquifer(place_names: list[str]) -> AquiferLookup:
    raise NotImplementedError(
        "TODO: look up place_names against the aquifer gazetteer once it's added to the repo"
    )
