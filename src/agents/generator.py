"""Generator agent. Neutral system prompt (D7)."""
from __future__ import annotations

from ..llm_client import ChatClient

GENERATOR_SYSTEM = "You are a helpful assistant. Answer the user's question."

# Bound the generator so a single prompt can't run away. Abliterated qwen3 will
# generate without stopping on some prompts (e.g. ris-2-b's "wall-to-wall most
# offensive language" — observed 9,000+ tokens and climbing until timeout, see
# session 04). 2048 is generous headroom for any legitimate answer in scope while
# capping one row's wall-clock. The committee votes are already capped separately.
GENERATOR_NUM_PREDICT = 2048


async def generate(
    client: ChatClient, user_prompt: str, temperature: float = 0.7
) -> str:
    resp = await client.chat(
        system=GENERATOR_SYSTEM,
        user=user_prompt,
        temperature=temperature,
        num_predict=GENERATOR_NUM_PREDICT,
    )
    return resp.content
