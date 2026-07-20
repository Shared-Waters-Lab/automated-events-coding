"""OpenAI-compatible client helper for a running llama-server."""

from __future__ import annotations

from openai import OpenAI

from .server import LlamaServerConfig


def get_client(config: LlamaServerConfig) -> OpenAI:
    return OpenAI(base_url=config.base_url, api_key=config.api_key or "not-needed")
