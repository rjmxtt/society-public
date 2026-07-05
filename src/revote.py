"""Re-vote: run a committee over ALREADY-GENERATED candidate responses.

Isolates the committee (persona) effect from generator variance. Instead of
re-generating, it reuses the `candidate` (and `prompt`) recorded in a prior
results JSONL and only re-runs the committee + adjudicator. Output rows match the
batch.py schema, so `src/analyze_v2.py` reads them directly (auto-routing to the
v3 compositions via the harassment_safety_analyst marker).

This is the clean A/B for a persona change (D29): the candidates are held fixed,
so any catch / false-refusal delta vs the source run is attributable to the
committee alone, not to generator sampling. Much cheaper than a fresh batch too —
votes only, no 2048-token generations.

Usage:
    uv run python -m src.revote \
        --in data/v2/results/qwen3-balanced-8-v2.jsonl \
        --config configs/v3/balanced-7.yaml \
        --out data/v3/results/qwen3-balanced-7-revote-ro-v3.jsonl
    # subset / smoke-test:
    #   --categories fully-owned,not-owned    --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from .agents.committee import cast_vote
from .agents.debate import run_debate
from .config import SocietyConfig, load_society
from .llm_client import ChatClient, make_client
from .pipeline.adjudicator import adjudicate
from .pipeline.pipeline import REFUSAL_MESSAGE


def _iter_rows(path: Path) -> Iterator[dict]:
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
        f"[{str(row['prompt_id']):28s} | {model_short:28s}] "
        f"{verdict:8s} ({d['reason']:18s}) "
        f"A={d['approves']} B={d['blocks']} P={d['parse_failures']}  "
        f"({row['timing_s']:.1f}s)  cat={row['category']}"
    )


def _debate_summary_line(row: dict) -> str:
    """Per-row development line for debate mode: R1 … → R2 … → R3 …, flagging the
    first round whose RELEASE/REFUSE outcome flips. E.g.

        [fo-...-L3 | qwen3] R1 A=4/B=3 RELEASED → R2 A=3/B=4 REFUSED → ...  flip@R2
    """
    model_short = row["model"].split("/")[-1][:30]
    rounds = row["debate"]["rounds"]
    parts, released_seq = [], []
    for rd in rounds:
        d = rd["decision"]
        verdict = "RELEASED" if d["released"] else "REFUSED"
        parts.append(f"R{rd['round']} A={d['approves']}/B={d['blocks']} {verdict}")
        released_seq.append(d["released"])
    flip = "no-flip"
    for i in range(1, len(released_seq)):
        if released_seq[i] != released_seq[i - 1]:
            flip = f"flip@R{i + 1}"
            break
    return (
        f"[{str(row['prompt_id']):28s} | {model_short:28s}] "
        f"{' → '.join(parts)}  {flip}  "
        f"({row['timing_s']:.1f}s)  cat={row['category']}"
    )


def _parse_prompt_ids(spec: str | None) -> list[str] | None:
    """Parse --prompt-ids: a comma list, or `@path` reading ids from a file
    (whitespace- or comma-separated, `#` comments ignored). None = no override."""
    if spec is None:
        return None
    if spec.startswith("@"):
        text = Path(spec[1:]).read_text()
        text = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        return [s for s in re.split(r"[\s,]+", text) if s]
    return [s.strip() for s in spec.split(",") if s.strip()]


def _approves(row: dict) -> int | None:
    d = row.get("decision") or {}
    return d.get("approves")


def _select_rows(
    rows: list[dict],
    n_members: int,
    contested: bool,
    controls: int,
    prompt_ids: list[str] | None,
) -> list[dict]:
    """Apply the v4 row-selection knobs (all additive; off by default → all rows).

    --prompt-ids overrides everything (explicit list, source order). Otherwise
    --contested narrows to the swing band approves ∈ {⌊n/2⌋, ⌊n/2⌋+1} (one vote
    from flipping an n-member majority; {3,4} for the 7-member committee), and
    --controls N adds N clearly-decided rows at the extremes (approves ∈
    {0,1,n-1,n}) that aren't already selected — debate should NOT wreck these.

    Controls are placed FIRST so the small fixed control set survives a tight
    `--limit` (which keeps the first N of the returned list); the contested rows
    fill the rest.
    """
    if prompt_ids is not None:
        idset = set(prompt_ids)
        return [r for r in rows if r.get("prompt_id") in idset]

    base = rows
    if contested:
        band = {n_members // 2, n_members // 2 + 1}
        base = [r for r in rows if _approves(r) in band]
    if controls > 0:
        extremes = {0, 1, n_members - 1, n_members}
        chosen = {r.get("prompt_id") for r in base}
        extra = [
            r
            for r in rows
            if _approves(r) in extremes and r.get("prompt_id") not in chosen
        ]
        base = extra[:controls] + base
    return base


async def _revote_one(
    client: ChatClient,
    society: SocietyConfig,
    row: dict,
    temperature: float,
    row_timeout: float | None,
    debate_rounds: int = 1,
) -> dict:
    t0 = time.monotonic()
    candidate = row.get("candidate")
    prompt = row.get("prompt", "")

    base = {
        "prompt_id": row.get("prompt_id"),
        "category": row.get("category"),
        "scenario": row.get("scenario"),
        "subtlety": row.get("subtlety"),
        "ground_truth": row.get("ground_truth"),
        "prompt": prompt,
        "model": client.model,
        "society_name": society.name,
        "candidate": candidate,
        # provenance: the run whose candidate we reused (held fixed for the A/B)
        "revote_source": {
            "model": row.get("model"),
            "society_name": row.get("society_name"),
        },
    }

    def _err(error: str) -> dict:
        return {
            **base,
            "votes": [],
            "decision": None,
            "released_text": None,
            "timing_s": time.monotonic() - t0,
            "error": error,
        }

    # Can't re-vote a row whose source generation failed / was a timeout.
    if not candidate:
        return _err("skipped: source row has no candidate")

    # v4 deliberation: N>=2 runs the multi-round debate over the fixed candidate.
    # Output stays back-compatible — top-level votes/decision = the final (round-N)
    # result so analyze_v2 reads it unchanged; per-round development under `debate`.
    if debate_rounds >= 2:
        async def _debate() -> "object":
            return await run_debate(
                client,
                society,
                prompt,
                candidate,
                n_rounds=debate_rounds,
                temperature=temperature,
            )

        try:
            if row_timeout is not None:
                result = await asyncio.wait_for(_debate(), timeout=row_timeout)
            else:
                result = await _debate()
            return {
                **base,
                "debate": {
                    "n_rounds": debate_rounds,
                    "rounds": [
                        {
                            "round": rd.round,
                            "votes": [asdict(v) for v in rd.votes],
                            "decision": asdict(rd.decision),
                        }
                        for rd in result.rounds
                    ],
                },
                "votes": [asdict(v) for v in result.rounds[-1].votes],
                "decision": asdict(result.final_decision),
                "released_text": result.released_text,
                "timing_s": time.monotonic() - t0,
                "error": None,
            }
        except asyncio.TimeoutError:
            return _err(f"RowTimeout: exceeded {row_timeout:.0f}s")
        except Exception as e:
            return _err(f"{type(e).__name__}: {e}")

    async def _vote_all() -> list:
        coros = [
            cast_vote(
                client,
                persona,
                prompt,
                candidate,
                temperature=temperature,
                visibility=society.visibility,
            )
            for persona in society.members
        ]
        return list(await asyncio.gather(*coros))

    try:
        if row_timeout is not None:
            votes = await asyncio.wait_for(_vote_all(), timeout=row_timeout)
        else:
            votes = await _vote_all()
        decision = adjudicate(votes, society.voting_rule)
        released_text = candidate if decision.released else REFUSAL_MESSAGE
        return {
            **base,
            "votes": [asdict(v) for v in votes],
            "decision": asdict(decision),
            "released_text": released_text,
            "timing_s": time.monotonic() - t0,
            "error": None,
        }
    except asyncio.TimeoutError:
        return _err(f"RowTimeout: exceeded {row_timeout:.0f}s")
    except Exception as e:  # cast_vote swallows its own errors, so this is rare
        return _err(f"{type(e).__name__}: {e}")


async def _amain() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--in",
        dest="in_paths",
        required=True,
        help="Comma-separated source results JSONL(s) (must carry `candidate`).",
    )
    p.add_argument("--config", required=True, help="Committee society YAML to re-vote with")
    p.add_argument("--out", required=True, help="Output JSONL path")
    p.add_argument(
        "--model",
        default=None,
        help="Committee model id. Default: the `model` of the first source row "
        "(the committee should match the generator model used originally).",
    )
    p.add_argument(
        "--categories",
        default=None,
        help="Optional comma-separated ownership categories to keep "
        "(e.g. 'fully-owned,not-owned'). Default: all.",
    )
    p.add_argument("--limit", type=int, default=None, help="Re-vote only the first N rows (smoke test).")
    p.add_argument(
        "--debate-rounds",
        type=int,
        default=1,
        help="v4 deliberation rounds. 1 (default) = single-round re-vote, current "
        "schema (no `debate` key). N>=2 = run the debate: personas see each other's "
        "prior-round votes and may revise; round N is final.",
    )
    p.add_argument(
        "--contested",
        action="store_true",
        help="Select only rows in the swing band (recorded approves ∈ {⌊n/2⌋,⌊n/2⌋+1}; "
        "{3,4} for a 7-member committee) — one vote from flipping. Default: all rows.",
    )
    p.add_argument(
        "--controls",
        type=int,
        default=0,
        help="Add N clearly-decided rows (approves at the extremes {0,1,n-1,n}) as "
        "debate controls — they should NOT move. Default 0.",
    )
    p.add_argument(
        "--prompt-ids",
        default=None,
        help="Explicit selection override: comma-separated prompt_ids, or `@path` to "
        "read them from a file. Overrides --contested/--controls.",
    )
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--backend", default=None, help="'ollama' or 'vllm' (default $SOCIETY_BACKEND then 'ollama').")
    p.add_argument("--base-url", default=None, help="Override server URL ($SOCIETY_LLM_URL then backend default).")
    p.add_argument(
        "--row-timeout",
        type=float,
        default=300.0,
        help="Per-row wall-clock cap (s). A hung row is logged RowTimeout and skipped. 0 disables. Default 300.",
    )
    p.add_argument("--timeout", type=float, default=600.0, help="Per-HTTP-call timeout (s). Default 600.")
    args = p.parse_args()
    row_timeout = args.row_timeout if args.row_timeout > 0 else None

    society = load_society(Path(args.config))

    keep_cats = (
        {c.strip() for c in args.categories.split(",") if c.strip()}
        if args.categories
        else None
    )
    rows: list[dict] = []
    for sp in (s.strip() for s in args.in_paths.split(",") if s.strip()):
        for r in _iter_rows(Path(sp)):
            if keep_cats is None or r.get("category") in keep_cats:
                rows.append(r)

    # v4 row selection (additive; no-op unless --contested/--controls/--prompt-ids).
    prompt_ids = _parse_prompt_ids(args.prompt_ids)
    rows = _select_rows(
        rows,
        n_members=len(society.members),
        contested=args.contested,
        controls=args.controls,
        prompt_ids=prompt_ids,
    )
    if args.limit is not None:
        rows = rows[: args.limit]

    # Committee model: explicit, else the source rows' generator model.
    model = args.model
    if model is None:
        model = next((r["model"] for r in rows if r.get("model")), None)
    if model is None:
        raise SystemExit("Could not determine committee model; pass --model.")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rt_str = f"{row_timeout:.0f}s" if row_timeout else "off"
    print(f"# Re-voting {len(rows)} rows with committee '{society.name}' "
          f"({len(society.members)} members, visibility={society.visibility})", flush=True)
    print(f"# Committee model: {model}  | candidates reused from source (held fixed)", flush=True)
    print(f"# Timeouts: row={rt_str}  http-call={args.timeout:.0f}s", flush=True)
    if args.debate_rounds >= 2:
        print(f"# Deliberation: {args.debate_rounds} rounds (round {args.debate_rounds} is final)", flush=True)
    print(f"# Output: {out_path}\n", flush=True)

    client = make_client(model=model, backend=args.backend, base_url=args.base_url, timeout=args.timeout)
    skipped = errors = 0
    try:
        with out_path.open("w") as out_f:
            for row in rows:
                out = await _revote_one(
                    client, society, row, args.temperature, row_timeout, args.debate_rounds
                )
                out_f.write(json.dumps(out) + "\n")
                out_f.flush()
                if out["error"]:
                    if out["error"].startswith("skipped"):
                        skipped += 1
                    else:
                        errors += 1
                    print(f"[{str(out['prompt_id']):28s}] {out['error']}", flush=True)
                elif "debate" in out:
                    print(_debate_summary_line(out), flush=True)
                else:
                    print(_summary_line(out), flush=True)
    finally:
        await client.aclose()

    print(f"\n# Done. {len(rows)} rows -> {out_path}  ({errors} errors, {skipped} skipped-no-candidate)")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
