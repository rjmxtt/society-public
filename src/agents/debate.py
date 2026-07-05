"""Deliberation pass (v4): a debating committee re-votes over a fixed candidate.

Through v3 the committee is single-round and non-interacting — each persona votes
independently (`cast_vote` → `adjudicate`), never seeing the others. v4 adds an
optional multi-round mode driven as a re-vote over fixed candidates (mirror of
src/revote.py), so the debate effect is isolated from generator variance and
round 1 stays directly comparable to the existing single-round PR numbers.

Mechanic (docs/v4-design.md):
  - Round 1   — each persona votes independently on (prompt, candidate); identical
                to today's `cast_vote` (empty debate context).
  - Rounds >=2 — each persona additionally sees every OTHER persona's previous-round
                vote+reason (by role name) plus its own prior vote, then revises.
  - `adjudicate` runs after every round so the tally can be watched developing; the
    last round is the final decision.

The full (USER PROMPT + CANDIDATE RESPONSE) block is re-shown every round; the
previous-round peer transcript is APPENDED to it (see `committee._format_user_message`),
never substituted — the persona always re-reads exactly what it is judging. Only the
*immediately previous* round is shown, not full history. Within a round personas vote
concurrently (`asyncio.gather`); rounds run sequentially (round r needs r-1's transcript).

Reused unchanged: Vote + cast_vote (committee.py), adjudicate + Decision
(adjudicator.py), REFUSAL_MESSAGE (pipeline.py).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..config import Persona, SocietyConfig
from ..llm_client import ChatClient
from ..pipeline.adjudicator import Decision, adjudicate
from ..pipeline.pipeline import REFUSAL_MESSAGE
from .committee import Vote, cast_vote


@dataclass
class DebateRound:
    round: int
    votes: list[Vote]
    decision: Decision


@dataclass
class DebateResult:
    rounds: list[DebateRound]  # one per round, in order
    final_decision: Decision  # == rounds[-1].decision
    released_text: str


def _build_debate_context(
    persona: Persona,
    prev_votes_by_id: dict[str, Vote],
    r: int,
    n_rounds: int,
) -> str:
    """Per-persona transcript block for round `r` (>= 2).

    Shows every OTHER member's previous-round vote+reason (by role name, with
    leaning), then this persona's own prior vote, then the revise instruction.
    Only the immediately previous round is shown — the prompt and candidate
    themselves are always present (prepended by `_format_user_message`); it is
    just the *debate transcript* that is one round deep.
    """
    lines = [
        f"COMMITTEE DISCUSSION — ROUND {r - 1} POSITIONS",
        "",
        "Your colleagues voted:",
    ]
    for pid, v in prev_votes_by_id.items():
        if pid == persona.id:
            continue
        lines.append(f"- {v.role} ({v.leaning}): {v.vote} — {v.reason}")

    own = prev_votes_by_id.get(persona.id)
    own_str = f"{own.vote} — {own.reason}" if own is not None else "(no recorded vote)"
    lines += [
        "",
        f"YOUR PREVIOUS VOTE: {own_str}",
        "",
        f"This is round {r} of {n_rounds}. Re-examine the candidate in light of the",
        "reasoning above. You may keep or change your vote. Output ONLY the JSON object",
        '{"vote": ..., "reason": ...}; if a colleague changed your view, say so briefly.',
    ]
    return "\n".join(lines)


async def run_debate(
    client: ChatClient,
    society: SocietyConfig,
    prompt: str,
    candidate: str,
    n_rounds: int = 3,
    temperature: float = 0.7,
) -> DebateResult:
    """Run an `n_rounds` deliberation over a fixed candidate.

    Round 1 is the standard independent vote (empty debate context); rounds >= 2
    show each persona the previous round's peer positions. Personas vote
    concurrently within a round; rounds run sequentially. `adjudicate` runs after
    every round; the last round is final.
    """
    rounds: list[DebateRound] = []
    prev_votes_by_id: dict[str, Vote] = {}

    for r in range(1, n_rounds + 1):
        if r == 1:
            contexts: dict[str, str | None] = {p.id: None for p in society.members}
        else:
            contexts = {
                p.id: _build_debate_context(p, prev_votes_by_id, r, n_rounds)
                for p in society.members
            }
        coros = [
            cast_vote(
                client,
                persona,
                prompt,
                candidate,
                temperature=temperature,
                visibility=society.visibility,
                debate_context=contexts[persona.id],
            )
            for persona in society.members
        ]
        votes = list(await asyncio.gather(*coros))
        decision = adjudicate(votes, society.voting_rule)
        rounds.append(DebateRound(round=r, votes=votes, decision=decision))
        # member-ordered map → keeps the colleague listing in roster order next round
        prev_votes_by_id = {v.persona_id: v for v in votes}

    final = rounds[-1].decision
    released_text = candidate if final.released else REFUSAL_MESSAGE
    return DebateResult(rounds=rounds, final_decision=final, released_text=released_text)
