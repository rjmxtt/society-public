# Society

Research prototype testing whether a **committee of persona-prompted agents** can recover alignment over a base model whose safety training has been ablated ("abliterated").

## Hypothesis

An intelligent individual is constrained not only by internal conscience but by the society they operate in — regulation, enforcement, policing. By analogy, a "society" of role-playing agents (e.g. police officer, child-safety officer, educator, civil-liberties lawyer) voting on a generator's response can intercept harmful outputs *even when the generator itself has no internal safety constraints*. We measure this as **catch rate** on red-team prompts traded off against **false-refusal rate** on benign prompts.

## Pipeline

```
user prompt → generator → committee (N personas, parallel votes) → adjudicator → response
```

All roles run on the same abliterated base model; differentiation is prompt-only. Fine-tuning per role is future work.

## Status

**Complete.** The project ran through five design iterations (v1–v5) including an external-benchmark evaluation against [DiaSafety](https://github.com/thu-coai/DiaSafety). The full write-up, methodology, and results are in [`user/blog.md`](user/blog.md).

Design and analysis docs:
- [docs/design.md](docs/design.md) — pipeline and components
- [docs/methodology.md](docs/methodology.md) — experimental setup and metrics
- [docs/decisions.md](docs/decisions.md) — design choices and rationale
- [docs/red-team-design.md](docs/red-team-design.md) — prompt scope and taxonomy
- [docs/related-work.md](docs/related-work.md) — comparison to prior multi-agent safety work
- `docs/v*-design.md`, `docs/v*-results.md` — per-iteration design and findings
- `sessions/` — dated working logs

## Note on withheld data

The red-team and benign **prompt corpora and per-run result logs are intentionally not published.** They contain prompts crafted to elicit harmful output from an unaligned model, plus the model's responses to them — dual-use content we chose not to distribute. The `data/` directory therefore ships empty. The methodology docs describe the corpus construction so the approach is reproducible in principle. The one external dataset used, DiaSafety, is publicly available from its authors (link above).

## Repo layout

```
src/          generator, committee agents, adjudicator, pipeline, evaluation, analysis
configs/      YAML society definitions (one per variant, versioned v1–v3)
docs/         design, methodology, decisions, per-iteration results, figures
sessions/     dated working logs
notebooks/    analysis and plotting notebooks
infra/        GPU provisioning + vLLM/Ollama bootstrap scripts
user/         blog write-up and its figures
data/         (empty — see "withheld data" above)
```

## Setup

Requires Python ≥3.11. Dependencies are managed with [uv](https://github.com/astral-sh/uv):

```bash
uv sync                      # core runtime
uv sync --group analysis     # + notebooks/plotting
```

You also need an LLM backend serving an OpenAI/Ollama-compatible endpoint. The
experiments used an abliterated model (`huihui_ai/qwen3-abliterated:14b`) served
via **Ollama** or **vLLM** on a rented GPU. See [`infra/README.md`](infra/README.md)
for provisioning and serving.

Configure the backend via environment variables:

```bash
export SOCIETY_BACKEND=ollama                 # or 'vllm'
export SOCIETY_LLM_URL=http://localhost:8000  # your server
```

## Usage

Single prompt through a society config:

```bash
uv run python -m src.run \
  --config configs/v3/balanced-7.yaml \
  --prompt "your prompt here"
```

Batch run over a prompt corpus (writes JSONL results):

```bash
uv run python -m src.batch \
  --config configs/v3/balanced-7.yaml \
  --prompts data/v3/prompts/fully-owned-v3.jsonl \
  --models huihui_ai/qwen3-abliterated:14b \
  --out data/v3/results/my-run.jsonl
```

(Prompt corpora are not distributed — see the withheld-data note above.)

## License

MIT — see [LICENSE](LICENSE).
