"""Shared LLM-client surface and backend factory.

Two backends implement the same `ChatClient` protocol:
  - OllamaClient  (src/ollama_client.py)   — local dev, `format: json`
  - VLLMClient    (src/vllm_client.py)      — GPU box, OpenAI-compatible
                                              `/v1/chat/completions` with
                                              `guided_json` structured output

The rest of the codebase (agents, pipeline, batch, run) depends only on this
protocol and the `make_client` factory, so swapping backends is a flag/env
change with no call-site edits.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatResponse:
    content: str
    raw: dict


class ChatClient(Protocol):
    """Minimal surface the pipeline depends on."""

    model: str

    async def aclose(self) -> None: ...

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        json_mode: bool = False,
        seed: int | None = None,
        num_predict: int | None = None,
    ) -> ChatResponse: ...

    async def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        seed: int | None = None,
        retries: int = 1,
        num_predict: int | None = None,
        schema: dict | None = None,
    ) -> dict: ...


def _extract_json(content: str) -> dict:
    """Parse a JSON object from a model response that may include preamble.

    Handles:
      - Bare JSON: `{"vote": ...}`
      - Reasoning-model `</think>` preambles (Qwen3 etc.): strip everything
        up to and including the closing think tag, then parse.
      - Plain text preamble before the JSON: locate the first '{' and parse
        from there.

    With vLLM `guided_json` the output is already schema-constrained, so this
    is effectively a no-op there; it still matters for the Ollama backend.
    """
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    content = content.strip()
    if not content:
        raise ValueError("empty content after preamble strip")
    if content[0] != "{":
        idx = content.find("{")
        if idx < 0:
            raise ValueError("no JSON object found in content")
        content = content[idx:]
    return json.loads(content)


def make_client(
    model: str,
    backend: str | None = None,
    base_url: str | None = None,
    timeout: float = 1200.0,
) -> ChatClient:
    """Construct a backend client.

    Resolution order for `backend`: explicit arg → $SOCIETY_BACKEND → "ollama".
    Resolution order for `base_url`: explicit arg → $SOCIETY_LLM_URL → backend default.
    Client classes are imported lazily to avoid an import cycle.
    """
    backend = (backend or os.environ.get("SOCIETY_BACKEND") or "ollama").lower()
    base_url = base_url or os.environ.get("SOCIETY_LLM_URL")

    if backend == "ollama":
        from .ollama_client import OllamaClient

        return OllamaClient(
            model=model,
            base_url=base_url or "http://localhost:11434",
            timeout=timeout,
        )
    if backend == "vllm":
        from .vllm_client import VLLMClient

        return VLLMClient(
            model=model,
            base_url=base_url or "http://localhost:8000",
            timeout=timeout,
        )
    raise ValueError(f"Unknown backend {backend!r} (expected 'ollama' or 'vllm')")
