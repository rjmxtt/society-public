"""Salvage the v2 corpus from a dead workflow run's cached agent outputs.

The author-v2-corpus workflow died at 105/121 agents (16 in-flight, never
returned). All 105 completed agents are in the run's journal.jsonl, tagged with
agentId; each agent's transcript (agent-<id>.jsonl) holds the prompt, which names
the category (authors) or the intended category + scenario stem (verifiers).

This reconstructs what the workflow's JS assembly step would have produced:
join verdicts to scenarios by stem, keep admissible (verdict.admissible AND
derived_category == intended), dedup, trim to 16/category, write the JSONL.
Scenarios whose verifier died (no verdict) are kept as a flagged backfill pool so
a category can still reach 16 for the user's validation session. Zero new tokens.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RUN = Path(
    "/Users/rjm/.claude/projects/-Users-rjm-Documents-dev-society/"
    "2ae3d986-58d3-4748-a8f0-a5655dead527/subagents/workflows/wf_5848d634-360"
)
OUT = Path("/Users/rjm/Documents/dev/society/data/v2/prompts")
CATS = ["fully-owned", "partial-owned", "not-owned"]
PREFIX = {"fully-owned": "fo", "partial-owned": "pa", "not-owned": "no"}
GT = {"fully-owned": "block", "partial-owned": "none", "not-owned": "release"}
TARGET = 16

_CAT_AUTHOR = re.compile(r'for the ownership category "([^"]+)"')
_CAT_VERIFY = re.compile(r'INTENDED category "([^"]+)"')
_STEM = re.compile(r"scenario stem: (\S+)")


def prompt_text(agent_id: str) -> str:
    """Concatenate the first user message of an agent transcript."""
    f = RUN / f"agent-{agent_id}.jsonl"
    if not f.exists():
        return ""
    for line in f.open():
        try:
            o = json.loads(line)
        except Exception:
            continue
        m = o.get("message")
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            return " ".join(
                b.get("text", "") for b in c if isinstance(b, dict)
            )
    return ""


def load() -> tuple[dict, list]:
    """Return (scenarios_by_key, verdicts) from the journal + transcripts.

    scenarios_by_key[(cat, stem)] = scenario dict (+ 'category').
    verdicts = list of {cat, stem, admissible, derived, invariant, in_scope}.
    """
    scenarios: dict = {}
    verdicts: list = []
    for line in (RUN / "journal.jsonl").open():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") != "result":
            continue
        res = o.get("result") or {}
        aid = o.get("agentId")
        txt = prompt_text(aid)
        if "scenarios" in res:  # author
            m = _CAT_AUTHOR.search(txt)
            cat = m.group(1) if m else None
            if cat not in CATS:
                continue
            for s in res["scenarios"]:
                stem = s.get("scenario")
                if not stem:
                    continue
                key = (cat, stem)
                if key not in scenarios:  # dedup: first author wins
                    s["category"] = cat
                    scenarios[key] = s
        elif "derived_category" in res:  # verify
            mc, ms = _CAT_VERIFY.search(txt), _STEM.search(txt)
            if not (mc and ms):
                continue
            verdicts.append(
                {
                    "cat": mc.group(1),
                    "stem": ms.group(1),
                    "admissible": bool(res.get("admissible")),
                    "derived": res.get("derived_category"),
                }
            )
    return scenarios, verdicts


def main() -> None:
    scenarios, verdicts = load()
    # Best verdict per (cat, stem): admissible-and-matching beats anything else.
    verdict_ok: dict = {}
    for v in verdicts:
        key = (v["cat"], v["stem"])
        ok = v["admissible"] and v["derived"] == v["cat"]
        verdict_ok[key] = verdict_ok.get(key, False) or ok

    OUT.mkdir(parents=True, exist_ok=True)
    grand = {}
    for cat in CATS:
        admissible, unverified = [], []
        for (c, stem), s in scenarios.items():
            if c != cat:
                continue
            if (cat, stem) in verdict_ok:
                if verdict_ok[(cat, stem)]:
                    admissible.append(s)
                # else: verified-and-rejected → drop
            else:
                unverified.append(s)  # verifier died → flagged backfill
        chosen = admissible[:TARGET]
        backfilled = 0
        if len(chosen) < TARGET:
            need = TARGET - len(chosen)
            chosen += unverified[:need]
            backfilled = min(need, len(unverified))

        rows = []
        for s in chosen:
            stem = s["scenario"]
            verified = (cat, stem) in verdict_ok and verdict_ok[(cat, stem)]
            note = (
                f"{s.get('rationale', '')} | invariance: {s.get('invariance_note', '')}"
                f" | {'verified' if verified else 'UNVERIFIED (verifier died; check in validation)'}"
            )
            for lv in sorted(s.get("levels", []), key=lambda x: x.get("subtlety", 0)):
                n = lv.get("subtlety")
                rows.append(
                    {
                        "id": f"{PREFIX[cat]}-{stem}-L{n}",
                        "scenario": stem,
                        "category": cat,
                        "subtlety": n,
                        "ground_truth": GT[cat],
                        "owner_clause": s.get("owner_clause", ""),
                        "shared_stem": s.get("shared_stem"),
                        "prompt": lv.get("prompt", ""),
                        "notes": note,
                    }
                )
        path = OUT / f"{cat}-v2.jsonl"
        with path.open("w") as f:
            f.write(
                f"# {cat}-v2 — {len(chosen)} scenarios × 5 subtlety levels = {len(rows)} prompts. "
                f"ground_truth={GT[cat]}. Salvaged from workflow wf_5848d634-360 (died 105/121). "
                f"AWAITING USER VALIDATION.\n"
            )
            for r in rows:
                f.write(json.dumps(r) + "\n")
        grand[cat] = {
            "scenarios": len(chosen),
            "prompts": len(rows),
            "admissible": len(admissible),
            "backfilled_unverified": backfilled,
            "rejected_or_missing": "see counts",
        }

    print("=== v2 corpus reconstruction (from cached workflow results) ===")
    total_p = 0
    for cat in CATS:
        g = grand[cat]
        total_p += g["prompts"]
        print(
            f"{cat:14s}: {g['scenarios']:2d}/{TARGET} scenarios "
            f"({g['prompts']} prompts) | verified-admissible avail={g['admissible']} "
            f"| unverified backfill used={g['backfilled_unverified']}"
        )
    print(f"TOTAL prompts written: {total_p}")
    print(f"Output: {OUT}/{{fully-owned,partial-owned,not-owned}}-v2.jsonl")


if __name__ == "__main__":
    main()
