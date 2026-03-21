import json
from collections.abc import Iterator

import anthropic

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MAX_TOKENS, MODEL
from core.prompts import load_prompt

client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

SYSTEM = load_prompt("rag_assistant")


def _build_message(query: str, context: list[dict]) -> str:
    ctx = json.dumps(context, ensure_ascii=False, indent=2)
    return f"Context:\n{ctx}\n\nQuery: {query}"


def ask(query: str, context: list[dict]) -> str:
    """Single-shot blocking answer generation."""
    r = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[{"role": "user", "content": _build_message(query, context)}],
    )
    block = r.content[0]
    if not isinstance(block, anthropic.types.TextBlock):
        raise ValueError(f"Unexpected response block type: {type(block)}")
    return block.text


def stream(query: str, context: list[dict]) -> Iterator[str]:
    """Stream answer tokens one by one."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[{"role": "user", "content": _build_message(query, context)}],
    ) as s:
        yield from s.text_stream
