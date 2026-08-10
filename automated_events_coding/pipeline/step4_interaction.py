"""Step 4 - (Inter)action Extraction (LLM).

Input: single Event (parallel branch off the same per-event loop as Step 2)
Output: interactions, actors, summary, type

Downstream: loop "for each actor/interaction" over Step 5.
"""

from __future__ import annotations

from openai import OpenAI

from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import InteractionExtraction


def extract_interactions(client: OpenAI, model: str, event_text: str) -> InteractionExtraction:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP4_INTERACTION_EXTRACTION},
            {"role": "user", "content": event_text},
        ],
    )
    content = response.choices[0].message.content
    return InteractionExtraction.model_validate_json(content)
