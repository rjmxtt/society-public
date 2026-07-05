"""MVP CLI: run the pipeline against a single inline prompt."""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .config import load_society
from .llm_client import make_client
from .pipeline.pipeline import run as run_pipeline

DEFAULT_MODEL = "huihui_ai/qwen3-abliterated:14b"


def _print_human(result) -> None:
    d = result.decision
    print(f"\n=== SOCIETY: {result.society_name} ===\n")
    print(f"USER PROMPT:\n{result.user_prompt}\n")
    print(f"CANDIDATE:\n{result.candidate}\n")
    if result.votes:
        print(
            f"VOTES  approve={d.approves}  block={d.blocks}  "
            f"parse_fail={d.parse_failures}"
        )
        for v in result.votes:
            print(f"  [{v.vote:14s}] {v.role:30s} ({v.leaning:11s}) — {v.reason}")
    verdict = "RELEASED" if d.released else "REFUSED"
    print(f"\nDECISION: {verdict} ({d.reason})\n")
    print(f"OUTPUT:\n{result.released_text}\n")


async def _amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, help="Path to society YAML config")
    p.add_argument("--prompt", required=True, help="User prompt (inline)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument(
        "--backend",
        default=None,
        help="LLM backend: 'ollama' or 'vllm'. Defaults to $SOCIETY_BACKEND then 'ollama'.",
    )
    p.add_argument(
        "--base-url",
        default=None,
        help="Override server URL. Defaults to $SOCIETY_LLM_URL then the backend default.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Per-HTTP-call timeout in seconds (connect+read). Default 600.",
    )
    p.add_argument(
        "--json-out", action="store_true", help="Print full result as JSON"
    )
    args = p.parse_args()

    society = load_society(Path(args.config))
    client = make_client(
        model=args.model,
        backend=args.backend,
        base_url=args.base_url,
        timeout=args.timeout,
    )
    try:
        result = await run_pipeline(
            client, society, args.prompt, temperature=args.temperature
        )
    finally:
        await client.aclose()

    if args.json_out:
        print(
            json.dumps(
                {
                    "society": result.society_name,
                    "user_prompt": result.user_prompt,
                    "candidate": result.candidate,
                    "votes": [asdict(v) for v in result.votes],
                    "decision": asdict(result.decision),
                    "released_text": result.released_text,
                },
                indent=2,
            )
        )
    else:
        _print_human(result)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
