"""Ties the per-step modules together into the full per-article pipeline.

Mirrors the control flow in docs/pr-data-pipeline-spec.md. Steps 2/2.1/2.2 and
Step 4 are run sequentially here even though the spec leaves open whether they
could run fully in parallel -- revisit once that's resolved.
"""

from __future__ import annotations

from openai import OpenAI

from automated_events_coding.pipeline import (
    step0_relevance,
    step1_events,
    step2_location,
    step3_event_lead,
    step4_interaction,
    step5_identification,
)
from automated_events_coding.pipeline.schemas import EventLead, EventRecord, InteractionType


def process_article(
    client: OpenAI, model: str, article_text: str, existing_records: list[EventRecord]
) -> list[dict[str, object]]:
    relevance = step0_relevance.check_relevance(article_text)
    if not relevance.relevant:
        return []

    event_list = step1_events.extract_events(client, model, article_text, relevance.meta)

    results: list[dict[str, object]] = []
    for event in event_list.events:
        event_lead = _run_location_branch(client, model, event.text)
        interactions = step4_interaction.extract_interactions(client, model, event.text)

        for item in interactions.interactions:
            if item.type == InteractionType.ACTION:
                identity = step5_identification.identify_action(client, model, item.summary)
            else:
                identity = step5_identification.identify_interaction(client, model, item.summary)

            # TODO: assemble an EventRecord from event_lead + identity and run
            # it through step6_dedup.check_duplicate(record, existing_records)
            # once the exact composition (in particular "bcode") is confirmed.
            results.append({"event_lead": event_lead, "identity": identity})

    return results


def _run_location_branch(client: OpenAI, model: str, event_text: str) -> EventLead:
    place_names = step2_location.extract_place_names(client, model, event_text)
    country_basin = step2_location.lookup_country_basin(place_names.place_names)
    aquifer = (
        step2_location.lookup_aquifer(place_names.place_names)
        if place_names.gw_mentioned
        else None
    )
    return step3_event_lead.extract_event_lead(client, model, event_text, country_basin, aquifer)
