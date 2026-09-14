"""Step 1 - Event Extraction (LLM).

Input: PR data (text) + Step 0 metadata
Output: events: Event[]

Downstream: loop "for each Event" over Steps 2 and 4.
"""

from __future__ import annotations

from functools import partial
from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_list_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import Event, EventList


def extract_events(
    client: OpenAI,
    model: str,
    article_text: str,
    meta: dict[str, str],
    max_retries: int = 2,
) -> EventList:
    """Extract events from an article via the LLM.

    If the model's response is not valid JSON or does not match the EventList
    schema, the failed attempt is sent back to the model with instructions to
    fix it. After ``max_retries`` additional attempts (i.e. ``max_retries + 1``
    total calls) an :class:`~automated_events_coding.llm.validation.LLMResponseError`
    is raised carrying the last raw response.
    """
    # Step 0 metadata (relevance label/score from the classifier) is passed
    # along per the spec; include it in the user message for now since the
    # Step 1 prompt doesn't reference it yet.
    meta_block = "\n".join(f"{key}: {value}" for key, value in meta.items())
    user_content = f"{article_text}\n\n[Step 0 metadata]\n{meta_block}"

    events = request_json(
        client,
        model,
        prompts.STEP1_EVENT_EXTRACTION,
        user_content,
        parse=partial(parse_json_list_as, item_model=Event),
        max_retries=max_retries,
    )
    return EventList(events=events)
