"""
Custom grader provider for promptfoo llm-rubric assertions.

Promptfoo passes the grading prompt as a JSON-encoded array of chat messages
(system + user) when using a Python provider for grading. This grader
forwards those messages to Anthropic using the same proxy client as the RAG.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import anthropic
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL

_client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
)

GRADER_MODEL = "claude-haiku-4-5"


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """Grade an LLM response against a rubric.

    Promptfoo passes `prompt` as either:
      - A JSON string encoding a list of chat messages: [{"role": ..., "content": ...}, ...]
      - A plain string rubric prompt

    Returns a dict with `output`, `pass`, `score`, `reason` so promptfoo
    can interpret the grading result directly.
    """
    try:
        # Attempt to parse as message array (promptfoo format)
        messages = json.loads(prompt)
        if not isinstance(messages, list):
            raise ValueError("not a list")
    except (json.JSONDecodeError, ValueError):
        # Fall back: treat the whole prompt as user content
        messages = [{"role": "user", "content": prompt}]

    # Split system message from user messages
    system_content = None
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system_content = msg["content"]
        else:
            user_messages.append({"role": msg["role"], "content": msg["content"]})

    if not user_messages:
        return {
            "output": "",
            "pass": False,
            "score": 0.0,
            "reason": "no user message in grading prompt",
        }

    kwargs: dict = {
        "model": GRADER_MODEL,
        "max_tokens": 256,
        "messages": user_messages,
    }
    if system_content:
        kwargs["system"] = system_content

    try:
        r = _client.messages.create(**kwargs)
        block = r.content[0]
        raw = block.text if isinstance(block, anthropic.types.TextBlock) else ""

        # Parse the JSON response the grading system prompt asks for
        result = json.loads(raw)
        return {
            "output": raw,
            "pass": bool(result.get("pass", False)),
            "score": float(result.get("score", 0.0)),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError:
        # Model replied but not valid JSON — check for obvious pass/fail language
        raw_lower = raw.lower()
        passed = "pass" in raw_lower and "fail" not in raw_lower
        return {
            "output": raw,
            "pass": passed,
            "score": 1.0 if passed else 0.0,
            "reason": raw[:200],
        }
    except Exception as exc:
        return {
            "output": "",
            "pass": False,
            "score": 0.0,
            "reason": f"grader error: {exc}",
        }
