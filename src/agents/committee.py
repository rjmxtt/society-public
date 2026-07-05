"""Committee agent. Each member returns a structured vote on a candidate response."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Persona
from ..llm_client import ChatClient


@dataclass
class Vote:
    persona_id: str
    role: str
    leaning: str
    vote: str  # "APPROVE" | "BLOCK" | "PARSE_FAILURE"
    reason: str


def _format_user_message(
    prompt: str,
    candidate: str,
    visibility: str = "prompt-and-response",
    debate_context: str | None = None,
) -> str:
    """Build the committee's user message.

    Under "response-only" (D24) the committee is blinded to the user prompt and
    judges the candidate alone — the matching voting protocol (composed into the
    persona system prompt at config load) names only CANDIDATE RESPONSE.

    `debate_context` (v4 deliberation) is APPENDED after the PROMPT/CANDIDATE
    block, never substituted for it — so the persona always re-reads exactly what
    it is judging and the only new material is the peer-positions transcript. When
    None (round 1 / pipeline / default revote) the message is byte-for-byte
    unchanged.
    """
    if visibility == "response-only":
        msg = f"CANDIDATE RESPONSE:\n{candidate}"
    else:
        msg = f"USER PROMPT:\n{prompt}\n\nCANDIDATE RESPONSE:\n{candidate}"
    if debate_context:
        msg = f"{msg}\n\n{debate_context}"
    return msg


COMMITTEE_NUM_PREDICT = 4000

# Vote contract. On the vLLM backend this is enforced as `guided_json` (the
# model physically cannot emit an off-schema vote); on Ollama it documents the
# expected shape and the parser below tolerates drift. Settles session 02's
# JSON-shape regression at the serving layer.
VOTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vote": {"type": "string", "enum": ["APPROVE", "BLOCK"]},
        "reason": {"type": "string"},
    },
    "required": ["vote", "reason"],
    "additionalProperties": False,
}


# Keys a model might use for the verdict instead of the contracted "vote".
_VOTE_KEYS = ("vote", "decision", "verdict", "recommendation", "judgement", "judgment")
# Keys it might use for the rationale.
_REASON_KEYS = ("reason", "rationale", "explanation", "justification")
# Tokens that map onto each verdict, checked as a prefix after upcasing.
_APPROVE_PREFIXES = ("APPRO", "ALLOW", "RELEASE", "PASS", "PERMIT", "OK", "YES")
_BLOCK_PREFIXES = ("BLOC", "REJEC", "REFUS", "DENY", "DENI", "NO")


def _normalize_vote(result: dict) -> tuple[str, str | None]:
    """Map a (possibly drifting) committee response to APPROVE / BLOCK.

    On the vLLM backend guided_json already guarantees the exact enum, so this
    is a no-op there. On Ollama (`format: json` constrains shape but not the
    value) it tolerates alternate keys, casing, word forms (approves/approval),
    and typos (APPROBLE) — the failure modes seen on gemma/qwen3 in session 02.

    Returns (vote, problem) where vote is APPROVE/BLOCK/PARSE_FAILURE and problem
    is a short note when nothing usable was found.
    """
    raw = None
    for k in _VOTE_KEYS:
        if result.get(k) not in (None, ""):
            raw = result[k]
            break
    if raw is None:
        return "PARSE_FAILURE", f"no vote key in {sorted(result)!r}"

    token = str(raw).strip().upper()
    if any(token.startswith(p) for p in _APPROVE_PREFIXES):
        return "APPROVE", None
    if any(token.startswith(p) for p in _BLOCK_PREFIXES):
        return "BLOCK", None
    return "PARSE_FAILURE", f"unexpected_vote_value: {raw!r}"


def _extract_reason(result: dict) -> str:
    for k in _REASON_KEYS:
        v = result.get(k)
        if v:
            return str(v)[:500]
    return ""


async def cast_vote(
    client: ChatClient,
    persona: Persona,
    prompt: str,
    candidate: str,
    temperature: float = 0.7,
    visibility: str = "prompt-and-response",
    debate_context: str | None = None,
) -> Vote:
    user_msg = _format_user_message(prompt, candidate, visibility, debate_context)
    try:
        result = await client.chat_json(
            system=persona.system_prompt,
            user=user_msg,
            temperature=temperature,
            num_predict=COMMITTEE_NUM_PREDICT,
            schema=VOTE_SCHEMA,
        )
        vote, problem = _normalize_vote(result)
        reason = problem if problem else _extract_reason(result)
    except Exception as e:
        vote = "PARSE_FAILURE"
        reason = f"{type(e).__name__}: {e}"
    return Vote(
        persona_id=persona.id,
        role=persona.role,
        leaning=persona.leaning,
        vote=vote,
        reason=reason,
    )
