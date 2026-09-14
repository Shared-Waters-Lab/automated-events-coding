"""Step 4 - (Inter)action Extraction (LLM).

Input: single Event (parallel branch off the same per-event loop as Step 2)
Output: interactions, actors, summary, type

Downstream: loop "for each actor/interaction" over Step 5.
"""

from __future__ import annotations

from functools import partial

from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import InteractionExtraction


def extract_interactions(
    client: OpenAI, model: str, event_text: str, max_retries: int = 2
) -> InteractionExtraction:
    return request_json(
        client,
        model,
        prompts.STEP4_INTERACTION_EXTRACTION,
        event_text,
        parse=partial(parse_json_as, model=InteractionExtraction),
        max_retries=max_retries,
    )
