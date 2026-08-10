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

from openai import OpenAI

from automated_events_coding.pipeline import prompts
from automated_events_coding.pipeline.schemas import ActionID, InteractionID


def identify_action(client: OpenAI, model: str, actor_summary: str) -> ActionID:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP5_1_ACTION_ID},
            {"role": "user", "content": actor_summary},
        ],
    )
    content = response.choices[0].message.content
    return ActionID.model_validate_json(content)


def identify_interaction(client: OpenAI, model: str, interaction_summary: str) -> InteractionID:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompts.STEP5_2_INTERACTION_ID},
            {"role": "user", "content": interaction_summary},
        ],
    )
    content = response.choices[0].message.content
    return InteractionID.model_validate_json(content)
