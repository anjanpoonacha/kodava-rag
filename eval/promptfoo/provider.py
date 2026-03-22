"""
Promptfoo Python provider for Kodava RAG.

Exported functions:
  call_api(prompt, options, context)       — full RAG pipeline (retrieve + generate)
  retrieve(prompt, options, context)        — BM25 retrieval only, no LLM call
  call_agent(prompt, options, context)     — SearchingExpert agent pipeline

Grading is handled by promptfoo's built-in Anthropic provider (no subprocess).
See defaultTest.options.provider in promptfooconfig.yaml.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.agent import run_with_trace
from core.llm import ask
from core.retriever import search, search_all


# ── Full RAG provider ──────────────────────────────────────────────────────────


def call_api(prompt: str, options: dict, context: dict) -> dict:
    """Retrieve corpus context then generate an answer with Claude.

    Returns output (answer string) and metadata (context hits) so promptfoo
    can run context-faithfulness assertions via contextTransform.
    """
    query = context.get("vars", {}).get("query", prompt)
    try:
        trace = run_with_trace(query)
        return {
            "output": trace.answer,
            "metadata": {
                "context_hits": len(trace.all_context),
                "context": trace.all_context,
                "search_calls": [
                    {"query": c.query, "collection": c.collection, "hits": c.hits}
                    for c in trace.search_calls
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Agent provider ─────────────────────────────────────────────────────────────


def call_agent(prompt: str, options: dict, context: dict) -> dict:
    """SearchingExpert agent — tool-use loop then answer generation.

    Appends a <!--META:{...}--> trailer to the output so promptfoo JS
    assertions can access search_calls via:
        JSON.parse(output.match(/<!--META:(.*?)-->/s)?.[1] ?? '{}')
    The trailer is invisible in rendered Markdown but parseable in assertions.
    """
    query = context.get("vars", {}).get("query", prompt)
    try:
        trace = run_with_trace(query)
        meta = {
            "search_calls": [
                {"query": c.query, "collection": c.collection, "hits": c.hits}
                for c in trace.search_calls
            ],
            "context_hits": len(trace.all_context),
        }
        meta_trailer = f"\n<!--META:{json.dumps(meta)}-->"
        return {
            "output": trace.answer + meta_trailer,
            "metadata": {**meta, "context": trace.all_context},
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Retrieval-only provider ────────────────────────────────────────────────────


def retrieve(prompt: str, options: dict, context: dict) -> dict:
    """Return raw BM25 retrieval results without calling the LLM.

    Output is a JSON string of corpus entries so promptfoo icontains/regex
    assertions can inspect it directly.
    """
    vars_ = context.get("vars", {})
    query = vars_.get("query", prompt)
    collection = vars_.get("collection", None)

    try:
        docs = search(query, collection) if collection else search_all(query)
        return {
            "output": json.dumps(docs, ensure_ascii=False, indent=2),
            "metadata": {"hits": len(docs)},
        }
    except Exception as exc:
        return {"error": str(exc)}
