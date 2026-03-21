import anthropic
import json
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MODEL, MAX_TOKENS
from core.prompts import load_prompt

client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

SYSTEM = load_prompt("rag_assistant")


def ask(query: str, context: list[dict]) -> str:
    ctx = json.dumps(context, ensure_ascii=False, indent=2)
    msg = f"Context:\n{ctx}\n\nQuery: {query}"
    r = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM,
        messages=[{"role": "user", "content": msg}],
    )
    block = r.content[0]
    if not isinstance(block, anthropic.types.TextBlock):
        raise ValueError(f"Unexpected response block type: {type(block)}")
    return block.text
