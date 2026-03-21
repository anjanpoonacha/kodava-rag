"""
SearchingExpert agent — agentic RAG loop.

The agent has one tool: search_kodava.  Claude decides:
  - What query to issue (may differ from the raw user question)
  - Which collection to target (or all)
  - Whether to retry with a reformulated query when results are thin

Tool description (reformulation rules, collection routing) is hot-loaded from
prompts/search_agent.md at module import time, matching the same pattern used
by core/llm.py for rag_assistant.md.  Update search_agent.md to change agent
search behaviour without rebuilding the image.

After the tool-use loop converges, the final answer is streamed back via a
separate messages.stream() call so callers get token-by-token output.

Public surface:
  run(query, history?)             → str   (blocking, full answer)
  stream(query, history?)          → Iterator[str]  (token-by-token)
  run_with_trace(query, history?)  → AgentTrace
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolParam

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MAX_TOKENS, MODEL
from core.prompts import load_prompt
from core.retriever import search, search_all

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_COLLECTIONS = ["vocabulary", "sentences", "grammar_rules", "phonemes"]

# Tool description hot-loaded from prompts/search_agent.md — same pattern as
# rag_assistant.md.  Loaded once at import time; restart the server (or
# kubectl rollout restart) to pick up prompt changes in production.
_SEARCH_TOOL_DESC: str = load_prompt("search_agent")

_SEARCH_TOOL_DICT: dict[str, Any] = {
    "name": "search_kodava",
    "description": _SEARCH_TOOL_DESC,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query. Prefer short keyword forms over full "
                    "natural-language sentences — BM25 scores are higher on "
                    "focused tokens. Examples: 'morning', 'past tense suffix', "
                    "'naan poane', 'LL phoneme'."
                ),
            },
            "collection": {
                "type": "string",
                "enum": _COLLECTIONS,
                "description": "Target a single collection. Omit to search all.",
            },
        },
        "required": ["query"],
    },
}
SEARCH_TOOL: ToolParam = cast(ToolParam, _SEARCH_TOOL_DICT)

# ---------------------------------------------------------------------------
# Trace dataclass (returned by run_with_trace for evals / logging)
# ---------------------------------------------------------------------------


@dataclass
class SearchCall:
    query: str
    collection: str | None
    hits: int
    docs: list[dict]


@dataclass
class AgentTrace:
    user_query: str
    search_calls: list[SearchCall] = field(default_factory=list)
    all_context: list[dict] = field(default_factory=list)
    answer: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=ANTHROPIC_BASE_URL,
    )


def _execute_tool(tool_input: dict) -> tuple[list[dict], SearchCall]:
    """Run search_kodava and return (docs, trace_entry)."""
    query: str = tool_input["query"]
    collection: str | None = tool_input.get("collection")
    docs = search(query, collection) if collection else search_all(query)
    call = SearchCall(
        query=query,
        collection=collection,
        hits=len(docs),
        docs=docs,
    )
    logger.debug(
        "search_kodava(query=%r, collection=%r) → %d hits", query, collection, len(docs)
    )
    return docs, call


def _tool_result_block(tool_use_id: str, docs: list[dict]) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(docs, ensure_ascii=False),
    }


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 2


def _agent_loop(
    query: str,
    history: list[dict] | None,
    system: str,
) -> tuple[list[dict], AgentTrace]:
    """
    Run the tool-use loop until Claude stops calling tools or _MAX_TOOL_ROUNDS
    is reached.

    Returns (accumulated_context, trace).
    """
    client = _make_client()
    trace = AgentTrace(user_query=query)

    messages: list[Any] = list(history or [])
    messages.append({"role": "user", "content": query})

    for _round in range(_MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=[SEARCH_TOOL],
            messages=messages,  # type: ignore[arg-type]
        )

        # Collect any text the model emitted alongside tool calls (rare but
        # possible — preserve for final answer assembly if stop_reason changed).
        assistant_blocks = response.content
        messages.append({"role": "assistant", "content": assistant_blocks})

        if response.stop_reason != "tool_use":
            # Model is done calling tools
            break

        # Execute every tool call in this response
        tool_results: list[dict] = []
        for block in assistant_blocks:
            if block.type != "tool_use":
                continue
            docs, call = _execute_tool(block.input)
            trace.search_calls.append(call)
            # Deduplicate context by id
            seen = {d.get("id") for d in trace.all_context}
            for doc in docs:
                if doc.get("id") not in seen:
                    trace.all_context.append(doc)
                    seen.add(doc.get("id"))
            tool_results.append(_tool_result_block(block.id, docs))

        messages.append({"role": "user", "content": tool_results})

    return messages, trace


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(query: str, history: list[dict] | None = None) -> str:
    """Full pipeline — tool-use loop then blocking answer generation."""
    system = load_prompt("rag_assistant")
    messages, trace = _agent_loop(query, history, system)

    # Extract the final assistant text block(s) from the last assistant message
    last = messages[-1]
    if last["role"] == "assistant":
        content = last["content"]
        if isinstance(content, list):
            texts = [b.text for b in content if hasattr(b, "text") and b.text]
            if texts:
                trace.answer = "\n".join(texts)
                return trace.answer

    # If the last message isn't an answer (e.g. it ended mid-tool-use), ask
    # for a final answer explicitly with accumulated context injected.
    client = _make_client()
    ctx_block = json.dumps(trace.all_context, ensure_ascii=False, indent=2)
    messages.append(
        {
            "role": "user",
            "content": (
                f"Based on the search results above, answer the original question.\n\n"
                f"Retrieved context:\n{ctx_block}\n\nQuery: {query}"
            ),
        }
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    )
    block = resp.content[0]
    if not isinstance(block, anthropic.types.TextBlock):
        raise ValueError(f"Unexpected response block type: {type(block)}")
    trace.answer = block.text
    return trace.answer


# Sentinel prefix used to pass context through the token stream to the API layer.
# The API layer strips this prefix and emits a separate SSE context event.
_CONTEXT_SENTINEL = "\x00ctx\x00"


def stream(query: str, history: list[dict] | None = None) -> Iterator[str]:
    """Tool-use loop (blocking) then stream the answer token by token.

    Yields answer tokens followed by a single sentinel string carrying the
    retrieved context as JSON.  Callers that only want text should filter out
    lines starting with _CONTEXT_SENTINEL.
    """
    system = load_prompt("rag_assistant")
    messages, trace = _agent_loop(query, history, system)

    # Always stream the final answer via messages.stream() so the caller
    # receives genuine token-by-token output regardless of which stop_reason
    # the tool-use loop produced.  Any text the loop already emitted is
    # discarded here — the streaming pass regenerates it with the accumulated
    # context injected, matching the behaviour of run_with_trace().
    client = _make_client()
    ctx_block = json.dumps(trace.all_context, ensure_ascii=False, indent=2)

    # Strip any trailing assistant turn so the conversation ends on a user
    # message before we append the final-answer prompt.
    if messages and messages[-1]["role"] == "assistant":
        messages = messages[:-1]

    messages.append(
        {
            "role": "user",
            "content": (
                f"Based on the search results above, answer the original question.\n\n"
                f"Retrieved context:\n{ctx_block}\n\nQuery: {query}"
            ),
        }
    )

    accumulated = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    ) as s:
        for text in s.text_stream:
            accumulated.append(text)
            yield text

    trace.answer = "".join(accumulated)
    yield _CONTEXT_SENTINEL + json.dumps(trace.all_context, ensure_ascii=False)


def run_with_trace(query: str, history: list[dict] | None = None) -> AgentTrace:
    """Run and return full trace including search calls and final answer."""
    system = load_prompt("rag_assistant")
    messages, trace = _agent_loop(query, history, system)

    last = messages[-1]
    if last["role"] == "assistant":
        content = last["content"]
        if isinstance(content, list):
            texts = [b.text for b in content if hasattr(b, "text") and b.text]
            if texts:
                trace.answer = "\n".join(texts)
                return trace

    client = _make_client()
    ctx_block = json.dumps(trace.all_context, ensure_ascii=False, indent=2)
    messages.append(
        {
            "role": "user",
            "content": (
                f"Based on the search results above, answer the original question.\n\n"
                f"Retrieved context:\n{ctx_block}\n\nQuery: {query}"
            ),
        }
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    )
    block = resp.content[0]
    if not isinstance(block, anthropic.types.TextBlock):
        raise ValueError(f"Unexpected response block type: {type(block)}")
    trace.answer = block.text
    return trace
