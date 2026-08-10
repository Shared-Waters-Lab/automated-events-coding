"""Step 0 - Relevance Check (classifier, not LLM).

Input: raw PR data (text)
Output: relevant: Y/N, meta: {...}

Backed by a fine-tuned BERT classifier (not yet trained -- see CLAUDE.md).
"""

from __future__ import annotations

from automated_events_coding.pipeline.schemas import RelevanceResult


def check_relevance(article_text: str) -> RelevanceResult:
    raise NotImplementedError(
        "TODO: load and call the fine-tuned BERT relevance classifier once trained"
    )
