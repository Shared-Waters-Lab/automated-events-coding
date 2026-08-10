"""Step 1 - Event Extraction (LLM).

Input: PR data (text) + Step 0 metadata
Output: events: Event[]

Downstream: loop "for each Event" over Steps 2 and 4.
"""

from __future__ import annotations

from openai import OpenAI

from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import EventList


def extract_events(
    client: OpenAI, model: str, article_text: str, meta: dict[str, str]
) -> EventList:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP1_EVENT_EXTRACTION},
            {"role": "user", "content": article_text},
        ],
    )
    content = response.choices[0].message.content
    return EventList.model_validate_json(content)
