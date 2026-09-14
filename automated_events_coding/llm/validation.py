"""Parsing/validation helpers for raw LLM responses.

LLM outputs are not guaranteed to be clean JSON: models often wrap the JSON in
```json ... ``` code fences, prepend explanatory prose, or emit trailing commas.
These helpers extract the first JSON value from a raw response string and
validate it against a Pydantic model (or an arbitrary type via TypeAdapter).

``request_json`` wraps any OpenAI-compatible chat client with a retry loop:
if the model's response is not valid JSON *and* does not validate against the
expected schema, the failed attempt is sent back to the model for another try.
Use it in every LLM-governed pipeline step so each step gets identical
JSON/schema validation and retry behavior.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError
from openai import OpenAI

T = TypeVar("T")

# Matches the outermost balanced JSON array or object (greedy, DOTALL).
_JSON_VALUE_PATTERN = re.compile(r"(\[.*\]|\{.*\})", re.DOTALL)


class LLMResponseError(Exception):
    """Raised when an LLM response fails JSON/schema validation after all retries.

    ``attempts`` is the total number of model calls made, and ``last_raw``
    carries the final raw response (if any) so callers can log it or feed it
    into a human-review queue.
    """

    def __init__(self, message: str, *, attempts: int = 0, last_raw: str | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_raw = last_raw


def extract_json(raw: str) -> Any:
    """Extract and parse the first JSON value from a raw LLM response.

    Tries ``json.loads`` on the full string first, then falls back to a regex
    match of the outermost ``[...]`` or ``{...}`` block (so surrounding prose
    and markdown code fences are tolerated).
    """
    if raw is None:
        raise ValueError("LLM returned no content")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = _JSON_VALUE_PATTERN.search(raw)
    if not match:
        raise ValueError(f"No JSON array or object found in LLM response: {raw!r}")
    return json.loads(match.group(1))


def is_valid_json(raw: str) -> bool:
    """Return True if ``raw`` contains a valid JSON value.

    Uses the same two-stage check as :func:`extract_json`: exact parse first,
    then the outermost array/object block. Returns False for None/empty input
    and anything without a parseable JSON value.
    """
    if not raw:
        return False
    try:
        extract_json(raw)
        return True
    except (ValueError, json.JSONDecodeError):
        return False


def parse_json_as(raw: str, model: type[BaseModel]) -> BaseModel:
    """Extract JSON from a raw LLM response and validate it as ``model``."""
    data = extract_json(raw)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"LLM response failed validation for {model.__name__}: {exc}") from exc


def parse_json_list_as(raw: str, item_model: type[BaseModel]) -> list[BaseModel]:
    """Extract a JSON array from a raw LLM response and validate items as ``item_model``."""
    data = extract_json(raw)
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        raise ValueError(f"Expected a JSON array in LLM response, got: {type(data).__name__}")
    adapter = TypeAdapter(list[item_model])  # type: ignore[valid-type]
    try:
        return adapter.validate_python(list(data))
    except ValidationError as exc:
        raise ValueError(
            f"LLM response failed validation for list[{item_model.__name__}]: {exc}"
        ) from exc


def request_json(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_content: str,
    parse: Any = None,
    *,
    max_retries: int = 2,
) -> Any:
    """Call the LLM and retry until the response is valid JSON matching the schema.

    ``parse`` is a callable mapping the raw response string to the validated
    result (e.g. ``functools.partial(parse_json_as, model=EventLead)`` or
    ``functools.partial(parse_json_list_as, item_model=Event)``). When omitted,
    only JSON validity is checked and the parsed JSON value is returned as-is.

    On failure (invalid JSON *or* schema validation error), the same payload is
    sent back to the model with its failed output and the validation error so
    it can retry. After ``max_retries`` additional attempts (i.e.
    ``max_retries + 1`` total calls) an :class:`LLMResponseError` is raised
    carrying the last raw response.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    last_raw: str | None = None
    attempts = 0
    for attempt in range(max_retries + 1):
        response = client.chat.completions.create(model=model, messages=messages)
        raw = response.choices[0].message.content
        try:
            if parse is not None:
                return parse(raw)
            if not is_valid_json(raw):
                raise ValueError("response contains no valid JSON value")
            return extract_json(raw)
        except Exception as exc:  # ValueError from the parse helpers, JSONDecodeError
            attempts += 1
            last_raw = raw
            if attempt >= max_retries:
                break
            # Send the same payload back to the model with its failed output so
            # it can retry producing a valid response.
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{user_content}\n\n"
                        f"Your previous response was not acceptable: {raw!r}\n"
                        f"Problem: {exc}\n"
                        "Return only the corrected JSON, with no prose or code fences."
                    ),
                },
            ]

    raise LLMResponseError(
        f"LLM did not return a valid response after {attempts} attempt(s)",
        attempts=attempts,
        last_raw=last_raw,
    )
