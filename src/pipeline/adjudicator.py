"""Adjudication — apply a voting rule to a list of votes.

Parse failures are treated as effective BLOCK votes (D10: fail-safe),
but logged separately so we can measure how often the model fails
structurally.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..agents.committee import Vote


@dataclass
class Decision:
    released: bool
    reason: str  # see set of possible reason codes below
    approves: int
    blocks: int
    parse_failures: int


# Possible Decision.reason values:
#   no_committee, majority_approved, majority_blocked, tie_refused


def adjudicate(votes: list[Vote], rule: str) -> Decision:
    approves = sum(1 for v in votes if v.vote == "APPROVE")
    blocks = sum(1 for v in votes if v.vote == "BLOCK")
    parse_failures = sum(1 for v in votes if v.vote == "PARSE_FAILURE")
    n = len(votes)

    if rule == "none":
        return Decision(
            released=True,
            reason="no_committee",
            approves=approves,
            blocks=blocks,
            parse_failures=parse_failures,
        )

    if rule == "simple_majority":
        released = approves * 2 > n
        if released:
            reason = "majority_approved"
        elif approves == blocks + parse_failures:
            reason = "tie_refused"
        else:
            reason = "majority_blocked"
        return Decision(
            released=released,
            reason=reason,
            approves=approves,
            blocks=blocks,
            parse_failures=parse_failures,
        )

    raise ValueError(f"Unknown voting rule: {rule!r}")
