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
from collections import defaultdict
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

# need a list of terms to exclude when doing the look up
EXCLUSION_TERMS = ["Dam", "Province", "Water Supply Scheme", "River"]


def _split_semicolon_list(value: object) -> list[str]:
    """Split a gazetteer ';'-delimited cell into trimmed, non-empty names."""
    return [name.strip() for name in str(value).split(";") if name.strip()]


@lru_cache(maxsize=None)
def _load_gazetteer() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Load the basin gazetteer once.

    
    """
    basins = pd.read_excel(_GAZETTEER_PATH, sheet_name=_BASIN_SHEET, engine="openpyxl")
    countries = pd.read_excel(
        _GAZETTEER_PATH, sheet_name=_COUNTRY_SHEET, engine="openpyxl"
    )

    basins["trib_bname"] = basins["Basin Name"] + "; " + basins["Tributary List"] 

    return basins, countries


def _normalize(name: str) -> re.Pattern[str] | None:
    """Compile a case-insensitive, word-bounded pattern for a place name.

    Returns None for names too short to match reliably (avoids one-letter
    river names like 'Tu' or 'Si' matching inside other words).
    """
    stripped = name.strip()
    if len(stripped) < 3:
        return None
    return re.compile(rf"\b{re.escape(stripped)}\b", re.IGNORECASE)

def _lookup_country_codes(country_list: list[str], countries: pd.DataFrame) -> list[str]:
    return [countries[countries["Country Name"] == country].CCODE.values[0] for country in country_list]

def lookup_country_basin(place_names: list[str]) -> list[CountryBasinLookup]:
    """Step 2.1 -- resolve place names to a TFDD basin code (rule-based).


    """
    if not place_names:
        return CountryBasinLookup(bcode=BCODE_GNRL, ccodes=[])

    basins, countries = _load_gazetteer()

    country_voting = defaultdict(int)
    basin_voting = defaultdict(int)

    for placename in place_names:
        if placename['placename_type'] == "country":
            clean_placename = placename['placename'].strip()
        poss_basins = basins[basins["Riparian Countries"].apply(lambda x: clean_placename in x.split("; "))].BCODE.to_list()
        for basin in poss_basins:
            country_voting[basin] += 1

    for placename in place_names:
        if placename['placename_type'] == "non-country":
            clean_placename = " ".join([word for word in placename['placename'].split(" ") if word not in EXCLUSION_TERMS]).strip()
            for bcode in country_voting:
                is_in_this_basin = basins[basins.BCODE == bcode]["trib_bname"].apply(lambda x: x.split("; ")).apply(lambda x: clean_placename in x).any()
                if is_in_this_basin:
                    basin_voting[bcode] += country_voting[bcode]

    max_vote = max(basin_voting.values())
    max_basins = [b for b in basin_voting.items() if b[1] == max_vote]
    max_basins = dict(max_basins)

    rip_countries = []
    for bcode in basin_voting.keys():
        rip_countries += basins[basins.BCODE == bcode]["Riparian Countries"].apply(lambda x: x.split("; ")).explode().to_list()
    rip_countries = list(set(rip_countries))
    
    poss_results = [
        CountryBasinLookup(bcode=bcode, ccodes=_lookup_country_codes(rip_countries, countries))
        for bcode in max_basins
    ]    
    return poss_results             

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
