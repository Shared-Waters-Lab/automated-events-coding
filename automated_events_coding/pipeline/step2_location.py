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

from openai import OpenAI

from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, PlaceNames


def extract_place_names(client: OpenAI, model: str, event_text: str) -> PlaceNames:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP2_LOCATION_EXTRACTION},
            {"role": "user", "content": event_text},
        ],
    )
    content = response.choices[0].message.content
    return PlaceNames.model_validate_json(content)


def lookup_country_basin(place_names: list[str]) -> CountryBasinLookup:
    raise NotImplementedError(
        "TODO: look up place_names against the country/basin gazetteer once it's added to the repo"
    )


def lookup_aquifer(place_names: list[str]) -> AquiferLookup:
    raise NotImplementedError(
        "TODO: look up place_names against the aquifer gazetteer once it's added to the repo"
    )
