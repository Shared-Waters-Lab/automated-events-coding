"""Step 0 - Relevance Check (classifier, not LLM).

Input: raw PR data (text)
Output: relevant: Y/N, meta: {...}

Backed by the fine-tuned BERT classifier at
https://huggingface.co/pnadel/article-classifier (a private repo -- requires a
Hugging Face token with access, loaded from the HF_TOKEN variable in .env).
"""

from __future__ import annotations

import os
from functools import lru_cache

import torch
from dotenv import load_dotenv
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from automated_events_coding.pipeline.schemas import RelevanceResult

# Load .env from the project root (repo layout: <root>/.env, package is two
# levels down). load_dotenv() does not override variables already set in the
# environment.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

MODEL_ID = "pnadel/article-classifier"

# Matches classifier-training/train.py: 0 = "N" (not relevant), 1 = "Y".
ID2LABEL = {0: "N", 1: "Y"}
POS_ID = 1
THRESHOLD = 0.5
MAX_LENGTH = 2048


def _get_token() -> str:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "HF_TOKEN is not set. Add it to .env at the project root, e.g.\n"
            "    HF_TOKEN=hf_..."
        )
    return token


@lru_cache(maxsize=1)
def _load_model():
    """Load the tokenizer + classifier once per process (they're expensive)."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=_get_token())
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID, token=_get_token()
    ).to(device)
    model.eval()
    return device, tokenizer, model


def check_relevance(article_text: str) -> RelevanceResult:
    device, tokenizer, model = _load_model()

    with torch.inference_mode():
        inputs = tokenizer(
            article_text,
            max_length=MAX_LENGTH,
            truncation=True,
            return_tensors="pt",
        ).to(device)
        logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0]
        pred_id = int(torch.argmax(probs))
        pos_prob = float(probs[POS_ID])

    label = ID2LABEL[pred_id]
    return RelevanceResult(
        relevant=label == "Y",
        meta={
            "relevance_label": label,
            "relevance_score": f"{pos_prob:.4f}",
        },
    )
