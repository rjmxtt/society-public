# Plan — benchmark the committee against public safety datasets (RADAR-comparable)

**Status: partially executed as v5 (DiaSafety).** The DiaSafety arm has been built and
run — committee-as-classifier via `src/revote.py`, no generation. First (interrupted) run +
the **ownership-gap finding** are written up in [v5a-results.md](v5a-results.md); a tuned
"owning" committee (v5b) is the queued follow-up. **Implicit-Toxicity and Red Team remain
deferred** (Red Team label threshold + Implicit-Toxicity license still unresolved). The
realized harness is simpler than this doc assumed: the planned `pipeline.py`/`batch.py`
candidate-passthrough edits were unnecessary (revote.py already votes over fixed
candidates), and no `datasets` dependency was added (the converter `src/eval/diasafety.py`
fetches over plain httpx). It builds on the positioning in [related-work.md](related-work.md)
(§1 RADAR, §8 the two challenges) and does **not** disturb the existing v2/v3 A/B corpus.

## Goal

Run our committee against the three public datasets RADAR
([arXiv:2509.25271](https://arxiv.org/abs/2509.25271)) evaluates on, to get numbers
that are *directly comparable* to a published multi-agent-safety baseline.

**What this buys us, beyond the comparison:**
- **External, multi-annotator ground truth.** Our current corpus is single-author,
  self-labeled. These datasets are third-party, expert/crowd-annotated.
- **Absolute classifier numbers** (catch / false-refusal against gold labels) we can
  put next to RADAR, WildGuard, MrGuard — not just our internal *relative* Pareto.
- **A generalization check** on the v3 precision claims (H1/H2): does a committee tuned
  on our taxonomy still separate safe/unsafe on a foreign taxonomy?

## Framing decision: committee-as-classifier (mode A)

These are all `(query, response) → safe/unsafe` **classification** sets; RADAR consumes
the responses already in the data (it is an *evaluator*, not a generate-then-gate
pipeline). Two ways to use them:

- **(A) Committee-as-classifier [CHOSEN].** Feed each dataset's `(context, response)`
  pair straight to the committee, **skipping our generator**, and score the committee
  block/approve against the gold label. This is the *only* mode comparable to RADAR.
  Our vote machinery already supports it: `cast_vote(client, persona, user_prompt,
  candidate, visibility=...)` takes both sides and a visibility flag, so PR (sees
  context+response) and RO (hide context) both work unchanged.
- **(B) Full generate-then-gate [OUT OF SCOPE here].** Regenerate responses with our
  abliterated model, then gate. Tests the whole pipeline, but our generated text ≠ the
  dataset's response, so the gold labels no longer apply → not comparable, needs fresh
  labeling. Revisit only if we want the end-to-end story on these queries.

## The datasets

| Dataset | Source | License | RADAR subset | Fields we map |
|---|---|---|---|---|
| **Red Team** (Ganguli et al. 2022) | [`Anthropic/hh-rlhf`](https://huggingface.co/datasets/Anthropic/hh-rlhf) `data_dir="red-team-attempts"` | MIT | 600 (300/300) | `transcript`, `rating`, `min_harmlessness_score_transcript` |
| **Implicit Toxicity** (Wen et al. 2023) | [`jiaxin-wen/Implicit-Toxicity`](https://huggingface.co/datasets/jiaxin-wen/Implicit-Toxicity) → `test.json` | confirm before redistribution | 400 (200/200) | `context`, `response`, `label` (int; 1=toxic) |
| **DiaSafety** (Sun et al. 2022) | [`thu-coai/diasafety`](https://huggingface.co/datasets/thu-coai/diasafety) | Apache-2.0 | 400 (200/200) | `context`, `response`, `category`, `label` (Safe/Unsafe) |

Load notes:
- DiaSafety / Red Team load cleanly via `datasets.load_dataset(...)`.
- Implicit-Toxicity: pull `test.json` directly (`huggingface_hub.hf_hub_download(
  "jiaxin-wen/Implicit-Toxicity", "test.json", repo_type="dataset")`). The HF
  auto-viewer errors on this repo because the *train* split is reward-model data
  (`win_response`/`lose_response`); `test.json` is the clean classification split.

## Harness changes (small, isolated)

1. **`src/pipeline/pipeline.py` — `run(...)`** (currently always generates at
   `pipeline.py:32`). Add an optional `candidate: str | None = None`. If provided, skip
   the `generate(...)` call and use it directly. Everything downstream
   (`cast_vote`, `adjudicate`, `visibility`) is unchanged.
   ```python
   async def run(client, society, user_prompt, temperature=0.7, candidate=None):
       if candidate is None:
           candidate = await generate(client, user_prompt, temperature=temperature)
       ...
   ```
2. **`src/batch.py` — `_run_one(...)`** (calls `run_pipeline` at `batch.py:70`). Pass
   `prompt.get("candidate")` through to `run`. When a corpus row carries `candidate`,
   no generation happens; when it doesn't (our existing corpora), behaviour is
   identical to today. The output row already records `candidate` and `ground_truth`
   (`batch.py:84-89`), so nothing else changes.
3. **Analyzer** — confirm `src/analyze.py` computes catch/FR from `ground_truth` +
   `decision.released` (it should, since those are the batch row fields). If it also
   subsets by `scenario`/`subtlety`/`owner_clause`, those will be absent here — emit
   them as `null` or a sentinel `category` so the foreign rows don't crash per-category
   rollups. Add an `external` source tag to keep them out of the v3 ownership analysis.

> No changes to `config.py`, `cast_vote`, or `adjudicate`. The single-model committee
> (D1/D20) and both visibility arms (D32) carry over as-is.

## Data conversion

Write `src/redteam/external_datasets.py` (or `src/eval/external_datasets.py`) that
downloads each set and emits one normalized JSONL per dataset into
`data/prompts/external/{redteam,implicit_toxicity,diasafety}.jsonl`, in the corpus
schema the batch runner already reads (`_iter_prompts`, `batch.py:21`):

```json
{"id": "diasafety-0001", "source": "diasafety", "category": "Offending User",
 "prompt": "<context>", "candidate": "<response>", "ground_truth": "should-refuse",
 "notes": "label=Unsafe"}
```

Per-dataset field mapping:
- **DiaSafety:** `prompt←context`, `candidate←response`, `category←category`,
  `ground_truth = should-refuse if label=="Unsafe" else should-answer`.
- **Implicit Toxicity:** `prompt←context`, `candidate←response`,
  `ground_truth = should-refuse if label==1 else should-answer`, `category="implicit"`.
- **Red Team:** take the **final assistant turn** of `transcript` as `candidate` and
  the preceding user turn as `prompt`; derive `ground_truth` by thresholding (see open
  decisions). `category="redteam"` (or carry the tag if present).

## Label → metric mapping

Gold label maps onto our existing metrics with no new metric code:
- gold **Unsafe / attack-success** → `should-refuse` → committee **block = catch**.
- gold **Safe / attack-failure** → `should-answer` → committee **block = false refusal**.

So per dataset we report **catch rate** and **false-refusal rate** (with Wilson CIs, per
`methodology.md`) for each operating point, plus the same catch-vs-FR scatter. RADAR
reports accuracy/F1 on the binary task — also compute overall accuracy / precision /
recall / F1 so at least one number is directly side-by-side with their table.

## Experiment grid

- **Datasets:** all three (subsample to RADAR's N — 600/400/400 — for a like-for-like
  row; see open decisions).
- **Committee:** the v3 sharpened roster (restrict-4 and balance-7 subsets, D29/D33).
  Optionally also the v2 roster to show the precision edits transfer to foreign data.
- **Visibility:** both **RO and PR** (D32). PR is the natural match to RADAR (it sees
  the query). RO is our harder, more interesting condition.
- **Operating points:** the two from D33 (restrictive-gated, everyone-can-block).
- **Single run**, temperature 0.7, as in v1–v3.

## Hypotheses

- **HE1 (generalization):** the v3 committee separates safe/unsafe on foreign taxonomies
  at above-chance catch/FR, i.e. the precision gains aren't overfit to our corpus.
- **HE2 (RADAR gap):** independent voting (D5) underperforms RADAR's debate on raw
  accuracy — quantify the gap; it sizes the v4 "add deliberation" prize (related-work
  §8a).
- **HE3 (implicit hardest):** catch is lowest on Implicit Toxicity (subtle by
  construction) — ties to our subtlety axis (D23); expect RO < PR there especially.

## Caveats / confounds (carry into any writeup)

- **Taxonomy ≠ ownership.** DiaSafety's five categories are context-sensitive dialogue
  harms, not our remits (D21/D22). This is an external-validity check, **not** a re-run
  of the ownership analysis. Report against their categories + coarse safe/unsafe only.
- **Scope shift vs D6.** These contain real hate speech / toxicity — more severe than
  our "refused-but-not-illegal" scope. Fine for eval; note it.
- **Not RADAR's exact rows.** Their success/failure splits aren't published; we
  replicate the *method* (sample N, threshold), not the identical sample.
- **Responses authored by other models** (ChatGPT/LLaMA/Anthropic models), not ours —
  the committee judges off-distribution text. That's the point (it's a classifier
  test), but worth stating.
- **Single base model committee (D1/D20)** unchanged — the PoLL diversity caveat
  (related-work §8b) still applies.

## Open decisions (resolve when picking this up)

- **Red Team label threshold.** Derive success/failure from `rating` (red-teamer Likert)
  or `min_harmlessness_score_transcript`? Pick one, document the cutoff, sanity-check a
  sample by hand. (RADAR's exact rule isn't given.)
- **Subsample to RADAR N or use full sets?** Matching N (600/400/400) is cleaner for
  comparison; full sets give tighter CIs. Could report both.
- **Multi-turn Red Team context.** Use only the final user→assistant exchange, or feed
  the whole transcript as `prompt`? Final exchange is simpler and matches how the
  committee reads a single candidate; note the choice.
- **Implicit-Toxicity license.** Confirm terms on the repo/HF page before
  redistributing any derived file; if unclear, keep the converter download-on-demand and
  don't commit the data.

## Step-by-step task list

1. [ ] Confirm Implicit-Toxicity license; decide commit-data vs download-on-demand.
2. [ ] Resolve the open decisions above (Red Team threshold, N, context, license).
3. [ ] Write `external_datasets.py`: download + normalize → `data/prompts/external/*.jsonl`.
4. [ ] Hand-verify ~10 converted rows per dataset (label mapping, candidate extraction).
5. [ ] Add `candidate` passthrough: `pipeline.run` + `batch._run_one` (the two small edits above).
6. [ ] Smoke-test: run 5 rows through `batch.py` in PR mode against the v3 config.
7. [ ] Make the analyzer tolerant of `external` rows (null scenario/subtlety; source tag).
8. [ ] Full batch: 3 datasets × {RO, PR} × v3 config.
9. [ ] Compute catch/FR (+ accuracy/precision/recall/F1) per dataset/arm; build the scatter.
10. [ ] Fold an "external benchmarks" subsection into `related-work.md` with the numbers,
       and quantify the RADAR gap (HE2).

## Proposed decision-log entries (when this ships)

- **D34 — External-benchmark mode.** Committee-as-classifier (mode A): supply a candidate
  response, skip the generator, score against third-party gold labels. New corpus under
  `data/prompts/external/`; held separate from the v2/v3 ownership A/B.
- **D35 — Datasets & label mapping.** Adopt RADAR's three public sets (Red Team /
  Implicit Toxicity / DiaSafety); map Unsafe/attack-success→should-refuse,
  Safe/attack-failure→should-answer; report catch/FR + accuracy/F1.
- **D36 — Generalization, not ownership.** External results are an external-validity
  check on the v3 precision claims; foreign taxonomies are reported as-is, not folded
  into the ownership categories (D21/D22).
