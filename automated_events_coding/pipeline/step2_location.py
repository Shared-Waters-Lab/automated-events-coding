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

import re
from functools import lru_cache, partial
from pathlib import Path

import pandas as pd
from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, PlaceNames

# Gazetteer backing Step 2.1 (TFDD basin dictionary). Note: this file does NOT
# cover aquifers -- Step 2.2 still needs its own lookup data.
_GAZETTEER_PATH = Path(__file__).resolve().parent.parent / "static" / "Dictionaries_20260803.xlsx"
_BASIN_SHEET = "Basin Names LU"
_COUNTRY_SHEET = "Country Names LU"

# Codebook special bcode values (see schemas.CountryBasinLookup).
BCODE_UNKN = "UNKN"  # basin not identifiable from the place names
BCODE_GNRL = "GNRL"  # no place names provided at all


def _split_semicolon_list(value: object) -> list[str]:
    """Split a gazetteer ';'-delimited cell into trimmed, non-empty names."""
    return [name.strip() for name in str(value).split(";") if name.strip()]


@lru_cache(maxsize=None)
def _load_gazetteer() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Load the basin gazetteer once.

    Returns (name_to_bcodes, ccodes_by_bcode) where ``name_to_bcodes`` maps
    every Tributary List and Riparian Countries entry (case-insensitive key)
    to the set of BCODEs it appears under, and ``ccodes_by_bcode`` maps each
    BCODE to its 3-letter country codes resolved via 'Country Names LU'.
    """
    basins = pd.read_excel(_GAZETTEER_PATH, sheet_name=_BASIN_SHEET, engine="openpyxl")
    countries = pd.read_excel(
        _GAZETTEER_PATH, sheet_name=_COUNTRY_SHEET, engine="openpyxl"
    )
    name_to_country: dict[str, str] = {
        str(name).strip().lower(): code for name, code in zip(countries["Country Name"], countries["CCODE"])
    }

    name_to_bcodes: dict[str, set[str]] = {}
    riparian_by_bcode: dict[str, list[str]] = {}
    for _, row in basins.iterrows():
        bcode = str(row["BCODE"]).strip()
        # Basin Name is included in the Tributary List for most rows but not
        # all -- include it explicitly so basin names always resolve.
        names = (
            _split_semicolon_list(row["Tributary List"])
            + [str(row["Basin Name"]).strip()]
            + _split_semicolon_list(row["Riparian Countries"])
        )
        for name in names:
            name_to_bcodes.setdefault(name.lower(), set()).add(bcode)

        riparian_names = _split_semicolon_list(row["Riparian Countries"])
        ccodes = sorted(
            {
                name_to_country[name.lower()]
                for name in riparian_names
                if name.lower() in name_to_country
            }
        )
        riparian_by_bcode[bcode] = ccodes

    return name_to_bcodes, {b: riparian_by_bcode.get(b, []) for b in basins["BCODE"]}


def _normalize(name: str) -> re.Pattern[str] | None:
    """Compile a case-insensitive, word-bounded pattern for a place name.

    Returns None for names too short to match reliably (avoids one-letter
    river names like 'Tu' or 'Si' matching inside other words).
    """
    stripped = name.strip()
    if len(stripped) < 3:
        return None
    return re.compile(rf"\b{re.escape(stripped)}\b", re.IGNORECASE)


def lookup_country_basin(place_names: list[str]) -> CountryBasinLookup:
    """Step 2.1 -- resolve place names to a TFDD basin code (rule-based).

    Each place name is matched (case-insensitively, word-bounded) against the
    gazetteer's Tributary List and Riparian Countries columns. All matches are
    intersected: the event's basin must contain every identified tributary AND
    border every identified riparian country. If exactly one BCODE survives,
    it is returned with that basin's riparian ccodes; if none or several
    survive, ``bcode`` is "UNKN" (or "GNRL" when no place names were given)
    and ``ccodes`` is empty -- the ambiguity should be resolved by a human.
    """
    if not place_names:
        return CountryBasinLookup(bcode=BCODE_GNRL, ccodes=[])

    name_to_bcodes, ccodes_by_bcode = _load_gazetteer()

    candidate_sets: list[set[str]] = []
    for place_name in place_names:
        pattern = _normalize(place_name)
        if pattern is None:
            continue
        matches: set[str] = set()
        for gazetteer_name, bcodes in name_to_bcodes.items():
            if pattern.search(gazetteer_name):
                matches |= bcodes
        # A place name that matches nothing in the gazetteer (e.g. a town like
        # 'Ondjiva') is ignored; it carries no basin information.
        if matches:
            candidate_sets.append(matches)

    if not candidate_sets:
        return CountryBasinLookup(bcode=BCODE_UNKN, ccodes=[])

    candidates = set.intersection(*candidate_sets)
    if len(candidates) == 1:
        bcode = next(iter(candidates))
        return CountryBasinLookup(bcode=bcode, ccodes=list(ccodes_by_bcode.get(bcode, [])))
    # Ambiguous (or empty after intersection): flag for human review.
    return CountryBasinLookup(bcode=BCODE_UNKN, ccodes=[])


def extract_place_names(
    client: OpenAI, model: str, event_text: str, max_retries: int = 2
) -> PlaceNames:
    return request_json(
        client,
        model,
        prompts.STEP2_LOCATION_EXTRACTION,
        event_text,
        parse=partial(parse_json_as, model=PlaceNames),
        max_retries=max_retries,
    )





def lookup_aquifer(place_names: list[str]) -> AquiferLookup:
    raise NotImplementedError(
        "TODO: look up place_names against the aquifer gazetteer once it's added to the repo"
    )
