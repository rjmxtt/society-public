"""Async vLLM client (OpenAI-compatible `/v1/chat/completions`).

Drop-in for OllamaClient. Two differences that matter:

  - `num_predict` maps to OpenAI `max_tokens`.
  - When `chat_json` is given a `schema`, it is sent as vLLM's `guided_json`
    extension. vLLM constrains decoding to that JSON Schema at the sampling
    layer, so the model *cannot* emit an off-schema vote. This eliminates the
    JSON-shape parse failures we saw under Ollama `format: json` (session 02).

Served by, e.g.:
    vllm serve huihui-ai/Qwen3-14B-abliterated --port 8000
The `model` field in requests must match the served model id.
"""
from __future__ import annotations

import json

import httpx

from .llm_client import ChatResponse, _extract_json


class VLLMClient:
    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:8000",
        timeout: float = 1200.0,
        api_key: str = "EMPTY",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

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
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if seed is not None:
            payload["seed"] = seed
        if num_predict is not None:
            payload["max_tokens"] = num_predict
        if schema is not None:
            # vLLM structured-output extension: hard-constrain decoding to the schema.
            payload["guided_json"] = schema
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = await self._client.post(
            f"{self.base_url}/v1/chat/completions", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResponse(content=content, raw=data)

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
