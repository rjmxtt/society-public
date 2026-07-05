"""Batch runner: run pipeline over JSONL prompts across one or more models.

Output: one JSONL row per (prompt, model). Streams to disk as it runs so a
crash mid-batch doesn't lose completed rows.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from .config import SocietyConfig, load_society
from .llm_client import ChatClient, make_client
from .pipeline.pipeline import run as run_pipeline


def _iter_prompts(path: Path) -> Iterator[dict]:
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            yield json.loads(line)


def _summary_line(row: dict) -> str:
    d = row["decision"]
    verdict = "RELEASED" if d["released"] else "REFUSED"
    model_short = row["model"].split("/")[-1][:30]
    return (
        f"[{row['prompt_id']:6s} | {model_short:32s}] "
        f"{verdict:8s} ({d['reason']:18s}) "
        f"A={d['approves']} B={d['blocks']} P={d['parse_failures']}  "
        f"({row['timing_s']:.1f}s)  cat={row['category']}"
    )


async def _run_one(
    client: ChatClient,
    society: SocietyConfig,
    prompt: dict,
    temperature: float,
    row_timeout: float | None = None,
) -> dict:
    t0 = time.monotonic()

    def _err_row(error: str) -> dict:
        return {
            "prompt_id": prompt["id"],
            "category": prompt.get("category"),
            "scenario": prompt.get("scenario"),
            "subtlety": prompt.get("subtlety"),
            "ground_truth": prompt.get("ground_truth"),
            "prompt": prompt["prompt"],
            "model": client.model,
            "society_name": getattr(society, "name", "?"),
            "candidate": None,
            "votes": [],
            "decision": None,
            "released_text": None,
            "timing_s": time.monotonic() - t0,
            "error": error,
        }

    try:
        coro = run_pipeline(
            client, society, prompt["prompt"], temperature=temperature
        )
        # Per-row wall-clock guard. On timeout, wait_for cancels the pipeline —
        # the in-flight HTTP requests close, so vLLM aborts those generations and
        # the GPU is freed rather than churning on a hung row.
        if row_timeout is not None:
            result = await asyncio.wait_for(coro, timeout=row_timeout)
        else:
            result = await coro
        return {
            "prompt_id": prompt["id"],
            "category": prompt.get("category"),
            "scenario": prompt.get("scenario"),
            "subtlety": prompt.get("subtlety"),
            "ground_truth": prompt.get("ground_truth"),
            "prompt": prompt["prompt"],
            "model": client.model,
            "society_name": result.society_name,
            "candidate": result.candidate,
            "votes": [asdict(v) for v in result.votes],
            "decision": asdict(result.decision),
            "released_text": result.released_text,
            "timing_s": time.monotonic() - t0,
            "error": None,
        }
    except asyncio.TimeoutError:
        return _err_row(f"RowTimeout: exceeded {row_timeout:.0f}s")
    except Exception as e:
        return _err_row(f"{type(e).__name__}: {e}")


async def _amain() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True, help="Society YAML config path")
    p.add_argument(
        "--prompts",
        required=True,
        help="Comma-separated JSONL file(s) of prompts. Multiple files are concatenated in order.",
    )
    p.add_argument(
        "--models", required=True, help="Comma-separated list of model names/ids"
    )
    p.add_argument("--out", required=True, help="Output JSONL path")
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
        "--row-timeout",
        type=float,
        default=600.0,
        help="Per-(prompt,model) wall-clock cap in seconds. A hung row is abandoned "
        "(logged as RowTimeout) and the batch continues, freeing the GPU. "
        "0 disables. Default 600.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Per-HTTP-call timeout in seconds (connect+read). Default 600.",
    )
    args = p.parse_args()
    row_timeout = args.row_timeout if args.row_timeout > 0 else None

    society = load_society(Path(args.config))
    prompt_paths = [Path(p.strip()) for p in args.prompts.split(",") if p.strip()]
    prompts: list[dict] = []
    for pp in prompt_paths:
        prompts.extend(_iter_prompts(pp))
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"# Running {len(prompts)} prompts × {len(models)} models "
        f"= {len(prompts) * len(models)} runs",
        flush=True,
    )
    print(
        f"# Config: {society.name}  ({len(society.members)} committee members)",
        flush=True,
    )
    rt_str = f"{row_timeout:.0f}s" if row_timeout else "off"
    print(
        f"# Timeouts: row={rt_str}  http-call={args.timeout:.0f}s",
        flush=True,
    )
    print(f"# Output: {out_path}\n", flush=True)

    with out_path.open("w") as out_f:
        for model in models:
            print(f"\n=== MODEL: {model} ===", flush=True)
            client = make_client(
                model=model,
                backend=args.backend,
                base_url=args.base_url,
                timeout=args.timeout,
            )
            try:
                for prompt in prompts:
                    row = await _run_one(
                        client, society, prompt, args.temperature, row_timeout
                    )
                    out_f.write(json.dumps(row) + "\n")
                    out_f.flush()
                    if row["error"]:
                        model_short = model.split("/")[-1][:30]
                        print(
                            f"[{prompt['id']:6s} | {model_short:32s}] "
                            f"ERROR: {row['error']}",
                            flush=True,
                        )
                    else:
                        print(_summary_line(row), flush=True)
            finally:
                await client.aclose()

    print(f"\n# Done. {len(prompts) * len(models)} rows written to {out_path}")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
