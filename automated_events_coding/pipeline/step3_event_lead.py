"""Step 3 - Event-lead Extraction (LLM).

Input: Event + Step 2.1 + Step 2.2 outputs
Output: see schemas.EventLead -- multiday, date, issue_area, scale_of_impact,
groundwater, infrastructure_involved, jbi_*, non_basin_entity_* (the spec's
original "issue_area_and_scale_of_impact" and "groundwater_infrastructure"
free-text fields were split per the codebook; see schemas.py).

Downstream: feeds Step 6.
"""

from __future__ import annotations

from functools import partial

from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, EventLead


def extract_event_lead(
    client: OpenAI,
    model: str,
    event_text: str,
    country_basin: CountryBasinLookup,
    aquifer: AquiferLookup | None,
    max_retries: int = 2,
) -> EventLead:
    context = country_basin.model_dump_json()
    if aquifer is not None:
        context += "\n" + aquifer.model_dump_json()

    return request_json(
        client,
        model,
        prompts.STEP3_EVENT_LEAD,
        f"{event_text}\n\n{context}",
        parse=partial(parse_json_as, model=EventLead),
        max_retries=max_retries,
    )
