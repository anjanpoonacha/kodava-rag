"""
Promptfoo Python provider for Kodava RAG.

Wraps the full RAG pipeline (retrieval + LLM) so promptfoo can drive it
with test cases and evaluate outputs end-to-end.

Two provider functions are exported:
  call_api(prompt, options, context)  — full RAG (retrieve + generate)
  retrieve(prompt, options, context)  — retrieval only (no LLM call)

Promptfoo passes the rendered prompt string as `prompt`.
Variables injected via the YAML config are available in context['vars'].
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.retriever import search_all, search
from core.llm import ask


# ── Full RAG provider ──────────────────────────────────────────────────────────


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """Retrieve context then generate an answer.

    The `prompt` variable is the user query (rendered from the YAML template).
    Returns a dict with `output` (answer string) and `metadata` (context hits).
    """
    query = context.get("vars", {}).get("query", prompt)
    try:
        ctx = search_all(query)
        answer = ask(query, ctx)
        return {
            "output": answer,
            "metadata": {
                "context_hits": len(ctx),
                "context": ctx,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Retrieval-only provider ────────────────────────────────────────────────────


def retrieve(prompt: str, options: dict, context: dict) -> dict:
    """Return raw retrieval results without calling the LLM.

    Used to evaluate the retrieval layer in isolation.
    Output is a JSON string of corpus entries for assertion matching.
    """
    vars_ = context.get("vars", {})
    query = vars_.get("query", prompt)
    collection = vars_.get("collection", None)

    try:
        if collection:
            docs = search(query, collection)
        else:
            docs = search_all(query)

        output = json.dumps(docs, ensure_ascii=False, indent=2)
        return {
            "output": output,
            "metadata": {"hits": len(docs)},
        }
    except Exception as exc:
        return {"error": str(exc)}
