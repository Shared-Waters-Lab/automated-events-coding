"""Step 5 - Action/Interaction ID (LLM).

Step 5.1 - Action ID (type == "action")
  Input: actor from Step 4
  Output: entity_name, entity_code

Step 5.2 - Interaction ID (type == "interaction", else branch)
  Input: actor pair from Step 4
  Output: entity_names, entity_codes, dyad_pairs (2 entities), dyad_code
    (per entity), bar_scale
"""

from __future__ import annotations

from functools import partial

from openai import OpenAI

from automated_events_coding.llm.validation import parse_json_as, request_json
from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import ActionID, InteractionID


def identify_action(
    client: OpenAI, model: str, actor_summary: str, max_retries: int = 2
) -> ActionID:
    return request_json(
        client,
        model,
        prompts.STEP5_1_ACTION_ID,
        actor_summary,
        parse=partial(parse_json_as, model=ActionID),
        max_retries=max_retries,
    )


def identify_interaction(
    client: OpenAI, model: str, interaction_summary: str, max_retries: int = 2
) -> InteractionID:
    return request_json(
        client,
        model,
        prompts.STEP5_2_INTERACTION_ID,
        interaction_summary,
        parse=partial(parse_json_as, model=InteractionID),
        max_retries=max_retries,
    )
