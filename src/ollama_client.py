"""Async Ollama HTTP client.

Wraps `/api/chat` with helpers for plain text and JSON-mode calls.
JSON mode uses Ollama's `format: json` constraint and adds one retry
on parse failure (D10).
"""
from __future__ import annotations

import json

import httpx

from .llm_client import ChatResponse, _extract_json

__all__ = ["OllamaClient", "ChatResponse"]


class OllamaClient:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float = 1200.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        json_mode: bool = False,
        seed: int | None = None,
        num_predict: int | None = None,
        schema: dict | None = None,
    ) -> ChatResponse:
        # `schema` is accepted for cross-backend parity; Ollama constrains
        # shape only via `format: json`, not a full JSON Schema.
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if seed is not None:
            payload["options"]["seed"] = seed
        if num_predict is not None:
            payload["options"]["num_predict"] = num_predict
        if json_mode:
            payload["format"] = "json"

        resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return ChatResponse(content=data["message"]["content"], raw=data)

    async def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        seed: int | None = None,
        retries: int = 1,
        num_predict: int | None = None,
        schema: dict | None = None,
    ) -> dict:
        last_err: Exception | None = None
        for _ in range(retries + 1):
            r = await self.chat(
                system,
                user,
                temperature=temperature,
                json_mode=True,
                seed=seed,
                num_predict=num_predict,
                schema=schema,
            )
            try:
                return _extract_json(r.content)
            except (json.JSONDecodeError, ValueError) as e:
                last_err = e
        raise ValueError(
            f"JSON parse failed after {retries + 1} attempts: {last_err}"
        ) from last_err
