# v5b results — owning the DiaSafety harms: the ownership lever, and a passive-failure A/B

> **Status: clean, complete run. n=400 (200 Unsafe / 200 Safe), single run, single
> abliterated model.** Unlike v5a (a partial, pod-killed run), this one finished cleanly:
> 0 errors, **4 parse-failure votes out of 2000 (0.2%)**, **0 rows with all-5 PF** (the
> pod-death signature; v5a had ~250). The headline numbers are therefore real
> measurements, not fail-safe artefacts. Run date 2026-06-11 (session 17). Setup mirrors
> `docs/v5a-results.md`; design + decisions below.

## What ran

- **Mode:** committee-as-classifier — **no generation.** Each DiaSafety (context, response)
  pair is fed to the committee as (prompt, candidate) via `src/revote.py`; the vote is scored
  against the gold Safe/Unsafe label by `src/analyze_external.py`.
- **Committee:** the **v5b tuned owning committee** — four NEW restrictive personas whose
  remits OWN the five DiaSafety psychosocial-harm categories that the v3 restrictive-only-4
  committee left unowned (the v5a finding), **plus** a fifth A/B challenger
  (`counter_speech_advocate`). Config `configs/v3/diasafety-owning-pr-5.yaml`, visibility
  **prompt-and-response** (every remit, and the challenger's harmful-premise gate, keys on the
  user prompt), `voting_rule: simple_majority` at run time; the headline **`unanimous_approve`**
  aggregation is reconstructed post-hoc, exactly as v5a.
- **The A/B (one run, two analyzer subsets):** single-round `revote` casts each persona's vote
  independently, so the four owning votes in the 5-member run are identical to a standalone
  owning-4 run. The same results file is scored as:
  - `diasafety-owning-4` — **baseline** (the four owners)
  - `diasafety-owning-5` — **treatment** (owners + `counter_speech_advocate`)
  The delta is the challenger's **pure marginal effect** on identical candidates (no generator
  variance). Under `unanimous_approve` it is monotone — the challenger can only add blocks.
- **Model / backend:** `huihui_ai/qwen3-abliterated:14b` on Ollama (A100-80GB pod) — same as v3/v4/v5a.
- **Corpus:** `data/external/prompts/diasafety.jsonl` — 400 rows, deterministic stratified
  200 Unsafe / 200 Safe, 80/category (40/40 per category) across DiaSafety's 5 harm types.

## The owning roster (one remit per harm family)

| persona (all restrictive) | owns | failure mode it blocks |
|---|---|---|
| `safeguarding_officer` | Risk Ignorance | distress/self-harm in the prompt met with dismissal, mockery, neglect, or encouragement |
| `anti_discrimination_advocate` | Biased Opinion **+** Toxicity Agreement | endorsing/agreeing with a hateful **or** abusive premise — **no named target, no slur, no protected group required** (broadened, D38) |
| `conduct_civility_moderator` | Offending User | gratuitous hostility / insult directed *at the user* |
| `professional_standards_reviewer` | Unauthorized Expertise | fabricated/unqualified high-stakes advice; invented authority (fake clinician) |
| `counter_speech_advocate` *(A/B challenger)* | the **passive-failure** residual | a response that meets a clearly harmful/distressing prompt premise with neutral non-handling (deflection, non-sequitur, empty pleasantry) instead of countering it or caring |

## ★ Headline 1 — the ownership lever: catch ~10% (unowned) → 53.5% (owned)

`diasafety-owning-4 × unanimous_approve` over all 400 rows:

| metric | value | 95% Wilson CI |
|---|---|---|
| **catch (recall)** | **53.5%** (107/200) | 46.6–60.3% |
| **false-refusal** | **33.0%** (66/200) | 26.9–39.8% |
| precision | 61.8% (107/173) | 54.4–68.8% |
| **accuracy** | **60.2%** (241/400) | 55.4–64.9% |
| F1 | 57.4% | |

Per category — **catch rose in every category** vs v5a's unowned 3–15%:

| category | v5a *unowned* catch | **owning-4 catch** | owning-4 false-refusal |
|---|---|---|---|
| Biased Opinion | 15% | **45.0%** (18/40) | 40.0% (16/40) |
| Offending User | 7% | **47.5%** (19/40) | 27.5% (11/40) |
| Risk Ignorance | 10% | **65.0%** (26/40) | 42.5% (17/40) |
| Toxicity Agreement | 3% | **60.0%** (24/40) | 20.0% (8/40) |
| Unauthorized Expertise | 14% | **50.0%** (20/40) | 35.0% (14/40) |

**This is the v5a finding turned into a causal demonstration.** v5a: catch collapsed to ~10%
because DiaSafety's psychosocial harms fell outside all four v3 remits — an *ownership gap*,
not a broken committee. v5b: add personas whose remits OWN those harms and catch jumps ~5×, in
every category. Catch tracks **ownership**, now shown causally (add the remit → catch rises),
generalising v3 headline #7 to a foreign taxonomy. It also yields the **first measurable
false-refusal number** for this corpus (v5a had no clean Safe rows): owning the harm costs
33% FR — the unavoidable other side of a veto-style (`unanimous_approve`) committee.

## ★ Headline 2 — the challenger A/B: a clean negative result

Adding `counter_speech_advocate` (`diasafety-owning-5`):

| | catch | false-refusal | accuracy |
|---|---|---|---|
| owning-4 (baseline) | 53.5% | 33.0% | **60.2%** |
| owning-5 (+challenger) | 76.5% | 63.5% | **56.5%** |
| **Δ (challenger marginal)** | **+23.0 pp** | **+30.5 pp** | **−3.7 pp** |

The challenger raised catch substantially — but FR more, and **accuracy fell**. Mechanically it
turned **46** released-Unsafe rows into catches (FN→TP) at the cost of **61** released-Safe rows
becoming false-refusals (TN→FP): a **marginal precision of 43% (46/107), below the 50% base
rate.** Sharper still: among the 227 rows the owning-4 committee released, the challenger fired
on **49.5%** of the Unsafe ones (46/93) and **45.5%** of the Safe ones (61/134) — it blocks
released-Unsafe and released-Safe at **nearly the same rate**. On the residual it is **barely
discriminating.**

**Interpretation — the residual is below the committee's resolution.** The rows the active-harm
owners leave behind are mostly *passive failures to challenge*: a neutral deflection or
non-sequitur to a toxic prompt. But DiaSafety's **Safe** set is full of the same neutral
deflections (the safe/unsafe boundary there is "avoided the active harm", not "actively
countered it"). So a persona that blocks passive non-handling cannot separate passive-Unsafe
from passive-Safe — it trades catch for false-refusal roughly 1:1-and-worse, exactly as
predicted before the run. This is the honest answer to "can owning the passive-failure mode
recover the missed catch?": **not at a price worth paying.** It echoes RADAR's observation that
even *single* frontier judges sit near chance on DiaSafety.

Per category, the challenger's effect confirms its scoping:

| category | owning-4 → owning-5 catch | owning-4 → owning-5 FR |
|---|---|---|
| Biased Opinion | 45% → **90%** | 40% → 75% |
| Offending User | 47.5% → **80%** | 27.5% → 77.5% |
| Risk Ignorance | 65% → **77.5%** | 42.5% → 62.5% |
| Toxicity Agreement | 60% → **85%** | 20% → 62.5% |
| Unauthorized Expertise | **50% → 50%** | 35% → 40% |

- Biggest swings are Biased Opinion / Offending User / Toxicity Agreement — the passive-failure-
  heavy categories — where catch *and* FR both balloon (the residual is irreducibly mixed).
- **Unauthorized Expertise catch is unchanged (50%→50%):** its harmful prompts are medical
  questions carrying no hate/abuse/distress premise, so the challenger's gate correctly never
  fires there. Confirms the challenger is a scoped counter-speech remit, not a block-everything
  switch — and that the A/B measures what it claims to.

## RADAR context

RADAR reports **79.0% accuracy** on DiaSafety (same 400-row, 200/200 shape) using **four frontier
models in multi-round debate** (GPT-5, Grok-3, Llama-3.1, DeepSeek-R1); *single* frontier judges
sit near chance (GPT-5 55.8%, Claude-Sonnet-4 56.5%), and a safety specialist (ShieldLM) reaches
61.3%. Our owning-4 committee lands at **60.2%** — squarely in the single-judge / ShieldLM band,
below the debate band. Note this is a committee **tuned to DiaSafety's taxonomy** (we built
remits for these exact five categories, an advantage RADAR's general committee did not have), yet
it still only reaches the single-judge band. The gap to 79% therefore reflects **judge quality
and method** (one single abliterated 14B model, one-shot independent votes, veto aggregation) vs
RADAR's **four frontier models debating** — *not* coverage. The owning-4 number is a constructive
demonstration of the ownership lever, deliberately distinct from an as-is external-validity claim.

## Caveats

- **Constructive demonstration, not as-is external validity.** The owning committee is tuned to
  DiaSafety's categories on purpose; 53.5%/33% answers "does the architecture catch these harms
  once remits cover them?", not "how does our system score on an unseen taxonomy?" The honest
  as-is number is the clean **untuned `restrictive-only-4`** run (still pending — the v5a attempt
  was pod-killed). See "Open next steps".
- **Single run, single abliterated model** (D1/D20); PoLL-diversity caveat applies. Temperature
  0.7, so per-vote sampling noise is present (CIs quoted).
- **`unanimous_approve` (any-1-blocks)** maximises both catch and FR; it is the named v3 best
  operating point reconstructed post-hoc. The full comp×rule grid is in the analyzer output
  (simple/supermajority are lower-catch/lower-FR points on the same votes).
- **Dialogue context** mapped to the single "USER PROMPT" slot; source carries raw HTML entities;
  responses authored by other models (the point of a classifier test).

## Decisions

- **D37 — Tuned owning committee (v5b).** Four new restrictive owning personas, one per DiaSafety
  harm family, covering all 5 categories; PR visibility; headline `unanimous_approve` post-hoc.
  *Rationale:* turns v5a's "10% because unowned" into a causal "53.5% when owned" demonstration of
  the ownership lever — explicitly a constructive demo, distinct from the as-is number.
- **D38 — Toxicity owner broadened to non-group toxicity.** `anti_discrimination_advocate` gained
  a TOXICITY prong (agreeing with abuse/cruelty/threats with no protected group), after a pre-run
  audit of all 200 Unsafe rows showed Toxicity Agreement is wider than group-prejudice. *Rationale:*
  an equalities-only persona would have under-tested its own assigned category.
- **D39 — Passive-failure A/B challenger (one-run / two-subset).** `counter_speech_advocate` added
  to a 5-member config; owning-4 vs owning-5 subsets of one run give the marginal A/B. Scope is
  *aggressive by design* (neutral dodging = failure), not FR-rigged. *Result:* +23 pp catch at
  +30.5 pp FR, accuracy −3.7 pp, marginal precision 43% — the passive residual is below the
  committee's resolution; owning it does not pay. A clean, pre-registered negative result.

## Reproduce

```
# 5-member committee, single run (committee-as-classifier, no generation):
SOCIETY_BACKEND=ollama SOCIETY_LLM_URL=http://localhost:8000 \
uv run python -m src.revote \
  --in data/external/prompts/diasafety.jsonl \
  --config configs/v3/diasafety-owning-pr-5.yaml \
  --model huihui_ai/qwen3-abliterated:14b \
  --out data/external/results/diasafety-owning-pr-5.jsonl

# A/B — both arms from the one file:
uv run python -m src.analyze_external --results data/external/results/diasafety-owning-pr-5.jsonl --composition diasafety-owning-4
uv run python -m src.analyze_external --results data/external/results/diasafety-owning-pr-5.jsonl --composition diasafety-owning-5
```
