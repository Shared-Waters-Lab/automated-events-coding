"""Step 2 - Location Extraction (LLM) + 2.1/2.2 gazetteer lookups (rule-based).

Step 2
  Input: single Event
  Output: place_names: string[]
  Downstream: feeds Steps 2.1 and 2.2

Step 2.1 - Country / Basin Lookup (rule-based)
  Input: place_names
  Output: bcode (TFDD basin code) + ccodes (country codes) -- see schemas.CountryBasinLookup
  Condition: runs unconditionally
  Method: countries vote for the basins they are riparian to; every other
    place name goes through the lookup cascade in pipeline/geo (tributary
    dictionary -> dam's river -> Wikidata river graph -> coordinates in basin
    polygons). See geo/resolver.py for the tiers and geo/voting.py for how
    their evidence is combined.

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
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd
from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.geo.config import GeoConfig
from automated_events_coding.pipeline.geo.evidence import Resolution, Strength
from automated_events_coding.pipeline.geo.normalize import EXCLUSION_TERMS  # noqa: F401  (re-exported)
from automated_events_coding.pipeline.geo.normalize import norm as _norm
from automated_events_coding.pipeline.geo.resolver import PlaceResolver
from automated_events_coding.pipeline.geo.voting import Decision, decide
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, PlaceNames

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Gazetteer backing Step 2.1 (TFDD basin dictionary). Note: this file does NOT
# cover aquifers -- Step 2.2 still needs its own lookup data.
_GAZETTEER_PATH = _STATIC_DIR / "Dictionaries_20260803.xlsx"
_BASIN_SHEET = "Basin Names LU"
_COUNTRY_SHEET = "Country Names LU"

# Codebook special bcode values (see schemas.CountryBasinLookup).
BCODE_UNKN = "UNKN"  # basin not identifiable from the place names
BCODE_GNRL = "GNRL"  # no place names provided at all


class PlaceName(TypedDict):
    placename: str
    placename_type: Literal["country", "non-country"]


COUNTRY_ALIASES: dict[str, str] = {
    "russia": "russian federation",
    # ...add as i find them
}


def _split_cell(cell) -> list[str]:
    """Split a '; '-separated cell tolerantly; drop empties and NaN. Returns normalized names."""
    return [n for n in (_norm(part) for part in _raw_split(cell)) if n]


def _raw_split(cell) -> list[str]:
    """Split a '; '-separated cell, keeping the original spelling."""
    if not isinstance(cell, str):
        return []
    return [part.strip() for part in cell.split(";") if part.strip()]


def _canonical_country(name: str) -> str:
    n = _norm(name)
    return COUNTRY_ALIASES.get(n, n)


@dataclass(frozen=True)
class _GazetteerIndex:
    country_to_basins: dict[str, frozenset]
    basin_countries: dict[str, tuple[str, ...]]
    country_codes: dict[str, str]
    trib_entries: tuple[tuple[str, str], ...]  # (bcode, name as written in the sheet)


@lru_cache(maxsize=None)
def _load_gazetteer() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the basin gazetteer once."""
    basins = pd.read_excel(_GAZETTEER_PATH, sheet_name=_BASIN_SHEET, engine="openpyxl")
    countries = pd.read_excel(_GAZETTEER_PATH, sheet_name=_COUNTRY_SHEET, engine="openpyxl")
    return basins, countries


@lru_cache(maxsize=1)
def _build_index() -> _GazetteerIndex:
    """Build lookup tables once. Call _build_index.cache_clear() if the sheet changes."""
    basins, countries = _load_gazetteer()

    country_to_basins: dict[str, set] = {}
    basin_countries: dict[str, set] = {}
    trib_entries: dict[tuple[str, str], None] = {}

    for bcode, basin_name, rip, tribs in zip(
        basins["BCODE"], basins["Basin Name"], basins["Riparian Countries"], basins["Tributary List"]
    ):
        if pd.isna(bcode):
            continue
        bcode = str(bcode)
        for c in _split_cell(rip):
            c = COUNTRY_ALIASES.get(c, c)
            country_to_basins.setdefault(c, set()).add(bcode)
            basin_countries.setdefault(bcode, set()).add(c)
        # Basin name and tributaries are read separately: concatenating the two
        # columns turned the whole cell into NaN whenever a basin had no
        # tributary list, which silently dropped the basin name.
        for name in _raw_split(basin_name) + _raw_split(tribs):
            trib_entries.setdefault((bcode, name), None)

    country_codes: dict[str, str] = {}
    for name, code in zip(countries["Country Name"], countries["CCODE"]):
        n = _canonical_country(name)
        if n and pd.notna(code):
            country_codes.setdefault(n, code)

    return _GazetteerIndex(
        country_to_basins={k: frozenset(v) for k, v in country_to_basins.items()},
        basin_countries={k: tuple(sorted(v)) for k, v in basin_countries.items()},
        country_codes=country_codes,
        trib_entries=tuple(trib_entries),
    )


@lru_cache(maxsize=1)
def _default_resolver() -> PlaceResolver:
    """Build the cascade once. Call _default_resolver.cache_clear() after rebuilding assets."""
    return PlaceResolver.from_config(GeoConfig.from_env(_STATIC_DIR), _build_index().trib_entries)


def _ccodes_for(bcode, idx: _GazetteerIndex) -> list[str]:
    codes = []
    for c in idx.basin_countries.get(bcode, ()):
        code = idx.country_codes.get(c)
        if code is None:
            logger.warning("No CCODE for riparian country %r (basin %s)", c, bcode)
            continue
        codes.append(code)
    return codes


@dataclass(frozen=True)
class BasinExplanation:
    """Everything behind a Step 2.1 decision, for auditing a wrong bcode."""

    decision: Decision
    country_votes: dict[str, int]
    strong_votes: dict[str, Fraction]
    weak_votes: dict[str, Fraction]
    resolutions: tuple[Resolution, ...]
    skipped_duplicates: tuple[str, ...]


def explain_country_basin(
    place_names: list[PlaceName], *, resolver: PlaceResolver | None = None
) -> BasinExplanation:
    """Step 2.1 with full provenance. lookup_country_basin is the thin wrapper."""
    idx = _build_index()
    resolver = resolver or _default_resolver()

    country_votes: Counter = Counter()
    seen_countries: set[str] = set()
    country_names: list[str] = []
    other_names: list[str] = []

    for p in place_names or ():
        raw = p.get("placename") if isinstance(p, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            continue
        ptype = p.get("placename_type")
        if ptype == "country":
            c = _canonical_country(raw)
            if c in seen_countries:
                continue
            seen_countries.add(c)
            country_names.append(raw)
            matched = idx.country_to_basins.get(c)
            if matched:
                country_votes.update(matched)
            else:
                logger.debug("Country %r not riparian to any basin", raw)
        elif ptype == "non-country":
            other_names.append(raw)
        else:
            logger.warning("Unknown placename_type %r for %r", ptype, raw)

    countries_iso2 = resolver.countries_iso2(country_names)

    strong: Counter = Counter()
    weak: Counter = Counter()
    seen_entities: set[str] = set()
    resolutions: list[Resolution] = []
    skipped: list[str] = []

    for raw in dict.fromkeys(other_names):
        r = resolver.resolve(raw, countries_iso2)
        resolutions.append(r)
        if not r.evidence:
            continue
        if r.entities <= seen_entities:
            skipped.append(raw)  # same feature(s) as an earlier name, e.g. "Amu Darya" / "Amudarya"
            continue
        seen_entities |= r.entities
        target = strong if r.strength is Strength.STRONG else weak
        for ev in r.evidence:
            target[ev.bcode] += ev.share

    decision = decide(country_votes, strong, weak)
    explanation = BasinExplanation(
        decision, dict(country_votes), dict(strong), dict(weak), tuple(resolutions), tuple(skipped)
    )
    logger.debug("Step 2.1: %s -> %s (%s)", [r.placename for r in resolutions],
                 decision.winners, decision.basis)
    return explanation


def lookup_country_basin(
    place_names: list[PlaceName], *, resolver: PlaceResolver | None = None
) -> list[CountryBasinLookup]:
    """Step 2.1 -- resolve place names to a TFDD basin code (rule-based).

    Ties return multiple results, sorted by bcode for determinism.

    TODO: should check if this is a useable event.
    """
    unknown = [CountryBasinLookup(bcode=BCODE_UNKN, ccodes=[])]
    if not place_names:
        return unknown
    decision = explain_country_basin(place_names, resolver=resolver).decision
    if not decision.winners:
        return unknown
    idx = _build_index()
    return [CountryBasinLookup(bcode=b, ccodes=_ccodes_for(b, idx)) for b in decision.winners]


def lookup_aquifer(place_names: list[str]) -> AquiferLookup:
    raise NotImplementedError(
        "TODO: look up place_names against the aquifer gazetteer once it's added to the repo"
    )