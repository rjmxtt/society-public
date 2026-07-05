"""Pipeline: generator -> parallel committee -> adjudicator."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..agents.committee import Vote, cast_vote
from ..agents.generator import generate
from ..config import SocietyConfig
from ..llm_client import ChatClient
from .adjudicator import Decision, adjudicate

REFUSAL_MESSAGE = "I'm not able to help with that request."


@dataclass
class PipelineResult:
    society_name: str
    user_prompt: str
    candidate: str
    votes: list[Vote]
    decision: Decision
    released_text: str


async def run(
    client: ChatClient,
    society: SocietyConfig,
    user_prompt: str,
    temperature: float = 0.7,
) -> PipelineResult:
    candidate = await generate(client, user_prompt, temperature=temperature)

    if society.voting_rule == "none" or not society.members:
        decision = adjudicate([], "none")
        return PipelineResult(
            society_name=society.name,
            user_prompt=user_prompt,
            candidate=candidate,
            votes=[],
            decision=decision,
            released_text=candidate,
        )

    vote_coros = [
        cast_vote(
            client,
            persona,
            user_prompt,
            candidate,
            temperature=temperature,
            visibility=society.visibility,
        )
        for persona in society.members
    ]
    votes = list(await asyncio.gather(*vote_coros))

    decision = adjudicate(votes, society.voting_rule)
    released_text = candidate if decision.released else REFUSAL_MESSAGE

    return PipelineResult(
        society_name=society.name,
        user_prompt=user_prompt,
        candidate=candidate,
        votes=votes,
        decision=decision,
        released_text=released_text,
    )
