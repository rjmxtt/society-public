# Related work

A survey of the arXiv literature adjacent to this project, with explicit positioning:
what is genuinely close, what only looks close, and the two findings in the literature
that directly challenge our design decisions. Written to seed the related-work section
of `blog.md` and to pre-empt the obvious reviewer objections.

> **Bottom line.** There is a busy, very recent (mostly 2025–2026) cluster of
> "multi-agent safety committee" work — the closest single paper is **RADAR**. But no
> paper found combines our actual setup: a *deliberately abliterated* generator + an
> external *persona committee* as the **recovery** mechanism, evaluated on a
> *catch-rate vs. false-refusal-rate Pareto* with the *ownership / constitution-as-sum-
> of-remits* framing (D21). We sit in a populated neighbourhood; the specific question
> is distinctive.

## 1. Closest: role-specialized multi-agent safety committees

The papers a reviewer would point at first. **Read RADAR before finalising the blog.**

- **RADAR — Risk-Aware Dynamic Multi-Agent Framework for LLM Safety Evaluation via
  Role-Specialized Collaboration** ([arXiv:2509.25271](https://arxiv.org/abs/2509.25271),
  Sep 2025). Four specialized roles run a multi-round debate over a partitioned risk
  space — explicit / implicit / non-risk — which maps almost one-to-one onto our
  owned / partial-owned / not-owned categories (D22). **Most direct overlap in the
  literature.** Its central finding is a direct challenge to us; see §6.
- **DialogGuard — Multi-Agent Psychosocial Safety Evaluation of Sensitive LLM
  Responses** ([arXiv:2512.02282](https://arxiv.org/pdf/2512.02282)). Roles split
  across categorisation / severity / policy-checking.
- **Agentic Moderation — Multi-Agent Design for Safer Vision-Language Models**
  ([arXiv:2510.25179](https://arxiv.org/html/2510.25179)). Same "specialize the remit,
  then combine" instinct, in the VLM setting.
- **Conversational Safety Framework** — distributes moderation across summarisation /
  categorisation / severity estimation / policy checking; reports that distribution
  beats single-agent and specialised-moderation baselines.

**How we differ:** these moderate an *already-aligned* model (or evaluate offline). We
gate the output of a generator with *no* internal safety, and the committee *is* the
alignment, not a second opinion on top of it.

## 2. Juries / panels of evaluators — the "committee" mechanism itself

- **Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse
  Models** (the "PoLL" paper, [arXiv:2404.18796](https://arxiv.org/abs/2404.18796)). A
  panel of diverse *smaller* models beats one large judge, with **less intra-model
  bias** and ~7× lower cost. This is the canonical "why a committee" citation — and
  also a caution: their headline benefit (bias reduction) comes from **model-family
  diversity**, which we deliberately forgo (D1/D20: one base model for all members,
  persona-only differentiation). See §6.

## 3. Multi-agent debate foundations — our intellectual lineage

- **Du et al., Improving Factuality and Reasoning in Language Models through Multiagent
  Debate** ([arXiv:2305.14325](https://arxiv.org/abs/2305.14325)). The "Society of
  Minds" paper; our "society" framing descends from here. Note their agents *debate*;
  ours *vote independently* (D5).
- **Should we be going MAD? A Look at Multi-Agent Debate Strategies for LLMs**
  ([arXiv:2311.17371](https://arxiv.org/pdf/2311.17371)). Useful survey for situating
  the debate-vs-independent-vote axis.

## 4. Constitutional approaches — our "constitution = sum of remits" framing (D21)

- **Constitutional AI: Harmlessness from AI Feedback**
  ([arXiv:2212.08073](https://arxiv.org/pdf/2212.08073)). The constitution is *trained
  into* the model via self-critique + RLAIF. We enforce a constitution **externally at
  inference**, never touching weights — a clean contrast to draw.
- **Collective Constitutional AI** ([arXiv:2406.07814](https://arxiv.org/html/2406.07814v1))
  and **Public Constitutional AI** ([arXiv:2406.16696](https://arxiv.org/pdf/2406.16696)).
  Sourcing / composing the constitution from plural input — thematically related to our
  "constitution is the union of persona remits" view.
- **C3AI — Crafting and Evaluating Constitutions for Constitutional AI**
  ([arXiv:2502.15861](https://arxiv.org/html/2502.15861v1)). Relevant to the v3
  precision work on ownership-boundary wording.

## 5. The generator side: abliteration (what makes our setup unusual)

- **Refusal in Language Models Is Mediated by a Single Direction** (Arditi et al.,
  [arXiv:2406.11717](https://arxiv.org/pdf/2406.11717)). The mechanism behind our
  "heretic"/abliterated generator.
- **An Embarrassingly Simple Defense Against LLM Abliteration Attacks**
  ([arXiv:2505.19056](https://arxiv.org/pdf/2505.19056)) and **Beyond Surface
  Alignment: Rebuilding LLMs' Safety Mechanism**
  ([arXiv:2509.15202](https://arxiv.org/pdf/2509.15202)).

  **Key framing point:** these treat the ablated model as an *attack to be defended
  against by restoring internal safety (retraining)*. We do the opposite — we *accept*
  the ablation and ask whether an *external committee* can recover alignment **without
  touching the weights**. No paper found pairs an intentionally-abliterated generator
  with an external committee as the recovery mechanism. **This is our clearest gap.**

## 6. The metric: over-refusal vs. catch — our Pareto axis

- **OR-Bench: An Over-Refusal Benchmark**
  ([arXiv:2405.20947](https://arxiv.org/pdf/2405.20947)) and **FalseReject**
  ([arXiv:2505.08054](https://arxiv.org/pdf/2505.08054)). Anchor our false-refusal axis.
- **Evaluating the Robustness of LLM Safety Guardrails Against Adversarial Attacks**
  ([arXiv:2511.22047](https://arxiv.org/html/2511.22047v1)) frames exactly our
  false-negative-vs-false-positive plane, with the "ideal bottom-left corner
  unoccupied" — useful language for positioning our Pareto curve.
- **WildGuard** ([arXiv:2406.18495](https://arxiv.org/html/2406.18495v3)) and **MrGuard**
  ([arXiv:2504.15241](https://arxiv.org/html/2504.15241.pdf)). Single guard-model
  baselines our committee implicitly competes with — a candidate external comparison
  point if we ever want an absolute, not just relative, reading.

## 7. Where this work looks novel

The combination I could **not** find already done:

1. **External persona committee as the *recovery* mechanism for a deliberately
   safety-ablated generator.** Everyone else either defends by retraining (§5) or
   moderates an already-aligned model (§1). We make the committee the *only* source of
   alignment.
2. **The ownership / visibility framing** — "constitution = sum of remits" (D21),
   response-only vs. prompt-and-response *visibility ceiling* (D24/D32), ownership
   category as the independent variable (D22). Nothing found is structured this way.
3. **Configurations as the independent variable** — roster, size, voting rule swept
   for a catch/FR Pareto, rather than proposing one fixed architecture and reporting a
   single operating point.

## 8. Two literature findings that directly challenge our design — and our rebuttals

These are the objections a reviewer *will* raise. Better to own them in the blog.

### 8a. RADAR: independent voting underperforms debate — vs. **D5**

RADAR reports that *"simple voting without interactive reasoning performs significantly
worse… free-form debate improves both accuracy and stability over independent voting."*
We chose the opposite: the committee votes **independently, no deliberation** (D5).

**Rebuttal to draft in the blog:**
- D5 is a *deliberate* methodological choice, not an oversight. Independent voting keeps
  the per-member signal clean — it lets us read each persona's marginal contribution
  (the vote-vector / per-role analysis that the whole v2→v3 ownership story is built
  on). Deliberation entangles members and destroys that decomposition.
- It also preserves the clean A/B across configurations: with deliberation, a roster
  change alters the *conversation*, not just the vote tally, confounding the
  comparison that is our primary result.
- RADAR optimises a single operating point for raw accuracy; we are mapping a *frontier*
  and attributing it to roles. Different goal → different design.
- Concede the point honestly and bank it: **deliberation is the obvious v4 lever** —
  expected to raise catch (RADAR's result) at some FR/cost; worth measuring against the
  independent-vote baseline this project establishes.

### 8b. PoLL: committee value comes from model diversity — vs. **D1/D20**

PoLL attributes a jury's advantage largely to **disjoint model families** reducing
intra-model bias. Our committee uses **one base model for every member** (D1/D20);
diversity is persona-prompt only.

**Rebuttal to draft in the blog:**
- The bias-reduction argument genuinely does *not* transfer to us, and we should say so
  plainly rather than imply committee = jury benefits.
- But our research question is *narrower and cleaner because of this*: "can role-prompting
  **alone** — holding the model fixed — recover alignment over an ablated generator?"
  Persona-only differentiation is the *point*, not a limitation: it isolates the effect
  of the constitution/remits from any confound of differing model capability.
- Multi-model committees are then a clearly-scoped future axis (and a likely strict
  improvement), not a gap in the current design.
- Cost framing aligns too: PoLL's "many small models beat one big judge cheaply" supports
  our small-local-model committee over a single frontier judge.

## Suggested reading order before writing the blog

1. **RADAR** ([2509.25271](https://arxiv.org/abs/2509.25271)) — engage §8a head-on.
2. **Replacing Judges with Juries / PoLL** ([2404.18796](https://arxiv.org/abs/2404.18796))
   — engage §8b.
3. **Beyond Surface Alignment** ([2509.15202](https://arxiv.org/pdf/2509.15202)) — to
   sharpen the "external recovery vs. internal retraining" contrast (§5, §7.1).
4. Skim **OR-Bench** / **FalseReject** for the over-refusal axis framing.
