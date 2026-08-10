"""Step 3 - Event-lead Extraction (LLM).

Input: Event + Step 2.1 + Step 2.2 outputs
Output: see schemas.EventLead -- multiday, date, issue_area, scale_of_impact,
groundwater, infrastructure_involved, jbi_*, non_basin_entity_* (the spec's
original "issue_area_and_scale_of_impact" and "groundwater_infrastructure"
free-text fields were split per the codebook; see schemas.py).

Downstream: feeds Step 6.
"""

from __future__ import annotations

from openai import OpenAI

from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import AquiferLookup, CountryBasinLookup, EventLead


def extract_event_lead(
    client: OpenAI,
    model: str,
    event_text: str,
    country_basin: CountryBasinLookup,
    aquifer: AquiferLookup | None,
) -> EventLead:
    context = country_basin.model_dump_json()
    if aquifer is not None:
        context += "\n" + aquifer.model_dump_json()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP3_EVENT_LEAD},
            {"role": "user", "content": f"{event_text}\n\n{context}"},
        ],
    )
    content = response.choices[0].message.content
    return EventLead.model_validate_json(content)
