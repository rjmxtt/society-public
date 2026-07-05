# Design

## Pipeline

```
              ┌─────────────┐
              │   Prompt    │
              └──────┬──────┘
                     ▼
         ┌────────────────────────┐
         │  Generator             │
         │  (gemma, neutral sys)  │
         └────────────┬───────────┘
                      ▼
         ┌────────────────────────┐
         │  Candidate response    │
         └────────────┬───────────┘
                      ▼
         ┌────────────────────────┐
         │  Committee (parallel)  │
         │  agent_1 ... agent_N   │
         │  each sees prompt +    │
         │  candidate, votes      │
         │  APPROVE / BLOCK +     │
         │  rationale             │
         └────────────┬───────────┘
                      ▼
         ┌────────────────────────┐
         │  Adjudicator           │
         │  (voting rule)         │
         └────────────┬───────────┘
                      ▼
              ┌─────────────┐
              │   Output    │
              └─────────────┘
```

## Components

### Generator

- Same base model, neutral system prompt: "You are a helpful assistant. Answer the user's question."
- One candidate response per call.
- Temperature: 0.7 default (revisited if results are noisy — see methodology).

### Committee

- N agents, all backed by the same base model.
- Each defined by a YAML config: `{ id, role, system_prompt, vote_weight }`.
- v1 default roster (balanced, N=7):

  | Persona | Leaning |
  |---|---|
  | Police officer | restrictive |
  | Child safety officer | restrictive |
  | Counter-extremism analyst | restrictive |
  | Content moderator | restrictive |
  | Schoolteacher / educator | permissive |
  | Journalist | permissive |
  | Civil-liberties lawyer | permissive |

- Each agent receives prompt + candidate response, returns structured JSON: `{ vote: "APPROVE" | "BLOCK", reason: str }`.
- Votes are independent — agents do not see each other's votes or rationales in v1 (avoids cascade effects, keeps votes statistically independent).

### Adjudicator

- v1 voting rule: simple majority of APPROVE votes → release candidate.
- Otherwise → generic refusal: "I'm not able to help with that request."
- Logs full vote tally + per-agent rationale regardless of outcome — refused responses are still recorded for analysis.

### Society config

A YAML file naming roster + voting rule. Configs are the primary independent variable.

v1 configs to compare:

| Config | Purpose |
|---|---|
| `baseline-none.yaml` | No committee — raw generator output (control) |
| `balanced-7.yaml` | v1 default roster |
| `restrictive-only-7.yaml` | 7 restrictive personas — measures restrictive bias |
| `permissive-only-3.yaml` | 3 permissive personas — measures permissive bias |
| `small-3.yaml` | 3-member balanced (1 restrictive, 1 permissive, 1 neutral) — committee-size effect |

## Open questions

- **Committee input scope.** v1 default: committee sees both prompt and candidate response. Alternative: response-only (forces the committee to evaluate content in isolation, may be more robust to leading prompts). Worth running as a variant once v1 baseline is set.
- **Judge model for harm scoring.** No locally available safety-tuned judge. Options in [methodology.md](methodology.md).
- **Should the committee model be the abliterated gemma?** v1: yes (the interesting research question). Future: try a non-abliterated open model as committee while keeping the abliterated generator.
