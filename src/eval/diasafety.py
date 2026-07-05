"""Convert DiaSafety (Sun et al. 2022) into our corpus JSONL for committee-as-classifier.

DiaSafety (`thu-coai/diasafety`, Apache-2.0) ships dialogue (context, response) pairs
with a gold Safe/Unsafe label across five context-sensitive harm categories. We map each
pair straight onto a corpus row the committee can vote on — NO generation, the dataset's
own response is the fixed `candidate`:

    context  -> prompt           (what the committee reads as the user prompt under PR)
    response -> candidate        (the text being judged)
    category -> category         (one of the 5 DiaSafety harm types; kept for breakdowns)
    label    -> ground_truth     Unsafe -> should-refuse,  Safe -> should-answer

The split is downloaded directly over HTTP (the repo stores plain `*.json` files at its
root, redirecting to the LFS cache — `follow_redirects=True` is required), so this needs
only `httpx` (already a core dep) — no `datasets` library.

Sampling is DETERMINISTIC (no RNG): within each label, rows are grouped by category, each
group sorted by (context, response), then picked round-robin across categories until the
per-label quota is met. This keeps all five categories represented and makes the 400-row
subset reproducible run-to-run. Defaults to RADAR's DiaSafety subset shape: 200 Unsafe /
200 Safe = 400.

Usage:
    uv run python -m src.eval.diasafety            # -> data/external/prompts/diasafety.jsonl
    uv run python -m src.eval.diasafety --n-per-label 200 --split test
    uv run python -m src.eval.diasafety --in-file /tmp/test.json   # use a local copy
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import httpx

REPO = "thu-coai/diasafety"
# Plain JSON arrays at the repo root; resolve/ 307-redirects to the LFS cache.
_URL = "https://huggingface.co/datasets/{repo}/resolve/main/{split}.json"
_SPLIT_FILE = {"test": "test", "validation": "val", "val": "val", "train": "train"}

_GT = {"Unsafe": "should-refuse", "Safe": "should-answer"}


def _load_split(split: str, in_file: str | None) -> list[dict]:
    if in_file:
        return json.loads(Path(in_file).read_text())
    fname = _SPLIT_FILE.get(split, split)
    url = _URL.format(repo=REPO, split=fname)
    resp = httpx.get(url, follow_redirects=True, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def _stratified(rows: list[dict], n: int) -> list[dict]:
    """Deterministically pick `n` rows, round-robin across categories so every
    category is represented. Rows within a category are sorted by (context,
    response) for reproducibility."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (r["category"], r["context"], r["response"])):
        by_cat[r["category"]].append(r)
    cats = sorted(by_cat)
    out: list[dict] = []
    depth = 0
    while len(out) < n:
        progressed = False
        for c in cats:
            if depth < len(by_cat[c]):
                out.append(by_cat[c][depth])
                progressed = True
                if len(out) >= n:
                    break
        if not progressed:  # exhausted every category before hitting n
            break
        depth += 1
    return out


def convert(split: str, n_per_label: int, in_file: str | None) -> list[dict]:
    raw = _load_split(split, in_file)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_label[r["label"]].append(r)

    out: list[dict] = []
    for label in ("Unsafe", "Safe"):  # block order: unsafe first, then safe
        picked = _stratified(by_label.get(label, []), n_per_label)
        if len(picked) < n_per_label:
            print(
                f"# WARNING: only {len(picked)} '{label}' rows available in {split} "
                f"(asked {n_per_label})",
                flush=True,
            )
        out.extend(picked)

    rows: list[dict] = []
    for i, r in enumerate(out, start=1):
        pid = f"diasafety-{i:04d}"
        rows.append(
            {
                # emit BOTH ids: `id` is the corpus convention (batch.py reads it);
                # `prompt_id` is what revote.py reads (it was built for result rows).
                "id": pid,
                "prompt_id": pid,
                "source": "diasafety",
                "category": r["category"],
                "prompt": r["context"],
                "candidate": r["response"],
                "ground_truth": _GT[r["label"]],
                "notes": f"label={r['label']}",
            }
        )
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        default="data/external/prompts/diasafety.jsonl",
        help="Output JSONL path (default: data/external/prompts/diasafety.jsonl)",
    )
    p.add_argument(
        "--n-per-label",
        type=int,
        default=200,
        help="Rows per label (Unsafe/Safe). Default 200 → 400 total (RADAR's shape).",
    )
    p.add_argument("--split", default="test", help="DiaSafety split (default: test)")
    p.add_argument(
        "--in-file",
        default=None,
        help="Use a local DiaSafety JSON instead of downloading (the raw test.json).",
    )
    args = p.parse_args()

    rows = convert(args.split, args.n_per_label, args.in_file)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    gt = Counter(r["ground_truth"] for r in rows)
    cat = Counter(r["category"] for r in rows)
    print(f"# Wrote {len(rows)} rows -> {out_path}")
    print(f"#   ground_truth: {dict(gt)}")
    print(f"#   category:     {dict(sorted(cat.items()))}")


if __name__ == "__main__":
    main()
