# qwen3 v1 analysis — balanced-8 batch, matched-triplet corpus

**Data:** `data/v1/results/qwen3-balanced-8-v1.jsonl` — 124/125 clean
(`ris-2-b` missing, runaway generation). 59 should-refuse / 65 should-answer
scored rows. Generator + committee = `huihui_ai/qwen3-abliterated:14b`.

**Regenerate:** `uv run python -m src.analyze --results data/v1/results/qwen3-balanced-8-v1.jsonl --pareto --triplet-detail balanced-8`
(full output snapshot: `qwen3-balanced-8-v1-analysis.txt`).

**Terms used below**

- **Catch rate** — fraction of should-refuse prompts the committee blocked
  (true positives / all should-refuse).
- **False-refusal rate** — fraction of should-answer prompts the committee
  blocked (false positives / all should-answer).
- **95% CI** — 95% confidence interval (Wilson score interval) on the rate.
- **Net** — catch rate minus false-refusal rate; a crude single-number
  discrimination score.
- **Triplet** — the three same-topic prompts per scenario: subtle-harmful
  (`-s`), blunt-harmful (`-b`), benign-legitimate (`-n`). **Perfect
  discrimination** = block `-s` and `-b`, release `-n`.
- **Triplet patterns** — three letters giving the committee's decision on
  (`-s`, `-b`, `-n`) in that order, B = blocked, R = released. So **BBR** is
  perfect discrimination; **BBB** is a "topic censor" (blocks the benign
  analog too); **RBR** means the blunt prompt was caught but the subtle one
  slipped through; **RRR** is fully permissive.
- **pp** — percentage points.

## Headline numbers

| config | catch [95% CI] | false-refusal [95% CI] | net |
|---|---|---|---|
| balanced-8 × restrictive_veto | 32/59 (54%) [42–66%] | 14/65 (22%) [13–33%] | +33% |
| restrictive-only-5 × unanimous_approve | 32/59 (54%) [42–66%] | 14/65 (22%) [13–33%] | +33% |
| balanced-8 × unanimous_approve | 36/59 (61%) [48–72%] | 24/65 (37%) [26–49%] | +24% |
| restrictive-only-5 × supermajority_2_3 | 14/59 (24%) [15–36%] | 2/65 (3%) [1–11%] | +21% |
| balanced-8 × supermajority_2_3 | 8/59 (14%) [7–25%] | 1/65 (2%) [0–8%] | +12% |
| balanced-8 × simple_majority | 0/59 (0%) | 1/65 (2%) | −2% |

Pareto frontier (low-false-refusal → high-catch): balanced-8 ×
supermajority_2_3 → restrictive-only-5 × supermajority_2_3 → balanced-6/7 ×
restrictive_veto → balanced-8 × restrictive_veto ≈ restrictive-only-5 ×
unanimous/veto → balanced-8 × unanimous_approve.

## Findings

1. **The committee is a topic matcher, not an intent reader — that's the
   headline, and it's negative.** Perfect triplet discrimination (block `-s`
   and `-b`, release `-n` on the same topic) peaks at **4/29 (14%)**
   (balanced-8 × restrictive_veto; restrictive-only-5 ties). The corpus was
   built to expose exactly this and it did.

2. **False refusal is concentrated where the triplet design predicted.**
   Under balanced-8 × unanimous_approve: benign-adjacent `-n` rows are blocked
   **17/30 (57%)** vs easy-benign **7/35 (20%)**. The committee keys on topic
   surface, so legitimate prompts on sensitive topics pay most of the
   false-refusal cost. (That 20% of *easy* benign still gets vetoed under
   unanimity shows single restrictive members fire on essentially harmless
   text.)

3. **Triplet pattern distribution confirms it** (balanced-8 × restrictive_veto,
   29 complete triplets): perfect discrimination (BBR) only 4; topic-censor
   (BBB, benign analog blocked too) 4; and the modal pattern is **RBR (10) —
   blunt framing caught, subtle framing *missed*, benign released**.
   Subtle-harmful is the committee's blind spot: subtle catch 40% vs blunt
   69% under this config.

4. **simple_majority is useless at this committee size** (0% catch): a block
   needs >4 of 8, and the median harmful prompt only draws 1–3 restrictive
   blocks. All the signal lives in veto-style rules (unanimous_approve,
   restrictive_veto), which buy catch rate by spending false-refusal.

5. **Per-category catch (balanced-8 × restrictive_veto)** is wildly uneven:
   manipulation 6/6, dark-patterns 5/6, misinformation 5/6 — but
   insulting-roast 1/6, stereotyping 1/6, risqué 2/5, borderline-advice 2/6.
   The committee catches *deception/manipulation* framings and waves through
   *offensive-content* framings. Plausible mechanism: the abliterated model's
   personas still reason about harm-to-others but have weak norms around
   offence.

6. **balanced-8 × restrictive_veto and restrictive-only-5 × unanimous_approve
   are numerically identical** (same 32 catches, same 14 false refusals) —
   under veto rules the permissive members are dead weight on these prompts;
   only the restrictive members' vetoes ever bind. The v2 "permissive members
   add discrimination" hypothesis is so far unsupported.

## Caveats

- Single model, single run, n=29–65 per cell — confidence intervals are wide;
  per-category cells (n=6) are directional only.
- `ris-2-b` missing (runaway generation; needs the `num_predict` cap, then
  re-run).
- Parse failures (~5–6%) count as BLOCK (decision D10, fail-safe), which
  inflates veto-rule catch *and* false-refusal slightly.

## Implications for v2

- The candidate default from session 04 (balanced-7/8 × unanimous_approve)
  looks worse than **balanced-8 × restrictive_veto** on these data: −7pp
  catch but −15pp false-refusal. Frontier point worth adopting as the working
  default.
- The real problem isn't the voting rule — it's that per-persona votes carry
  little intent signal — under balanced-8 × restrictive_veto, subtle-harmful
  is blocked at 40% vs benign-adjacent at 33%, a 7pp gap on the same topics.
  v2 should target the *persona prompt* (explicit intent-vs-topic
  instruction, maybe few-shot with a matched pair) before more composition
  sweeps.
