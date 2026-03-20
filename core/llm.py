import anthropic
import json
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MODEL

client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

SYSTEM = """Kodava takk language assistant for Kannada speakers.
Given retrieved context, help with transliteration, grammar rules, and sentence construction.
When a corpus entry has an empty kannada field, render the Kodava form in Kannada script on demand.
Devanagari renderings are available in context where pre-computed; use them as-is.
Always flag uncertain sounds with ⚠️, grammar traps with 🔴, stem changes with 🟡."""


def ask(query: str, context: list[dict]) -> str:
    ctx = json.dumps(context, ensure_ascii=False, indent=2)
    msg = f"Context:\n{ctx}\n\nQuery: {query}"
    r = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": msg}],
    )
    return r.content[0].text
