import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import DATA, PROMPT_FETCH, PROMPT_BRANCH, PROMPT_REPO
from core.agent import run_with_trace
from core.agent import stream as agent_stream, _CONTEXT_SENTINEL
from core.github_sync import append_corpus_entry
from core.llm import SYSTEM, ask
from core.retriever import invalidate, search_all, search_all_async
from core.vector_index import load as load_vector_index

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    source = (
        f"github:{PROMPT_REPO}@{PROMPT_BRANCH}"
        if PROMPT_FETCH
        else "local file (PROMPT_FETCH=false)"
    )
    logger.info("system prompt: %s (%d chars)", source, len(SYSTEM))
    print(f"[startup] system prompt loaded from {source} ({len(SYSTEM)} chars)")
    # Pre-load vector index so the first query doesn't pay the disk-read cost.
    # Returns None gracefully if embeddings haven't been built yet.
    load_vector_index()
    yield


app = FastAPI(title="Kodava RAG", lifespan=lifespan)

CORPUS = DATA / "corpus"
STATIC = Path(__file__).parent.parent / "static"

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/")
    def index():
        return FileResponse(str(STATIC / "index.html"))


class Query(BaseModel):
    q: str


class AgentQuery(BaseModel):
    q: str
    history: list[dict] | None = None


class Feedback(BaseModel):
    query: str
    answer: str
    correction: str | None = None
    status: str  # "approved" | "corrected" | "rejected"


@app.post("/query")
def query(body: Query):
    """Single-shot RAG via SearchExpert agent.

    Routes through the same agent loop as /agent/query so that query
    understanding and reformulation is handled by the model, not by
    hand-maintained regex heuristics.
    """
    trace = run_with_trace(body.q)
    return {
        "answer": trace.answer,
        "context": trace.all_context,
    }


@app.post("/agent/query")
def agent_query(body: AgentQuery):
    """Agentic RAG — SearchingExpert tool-use loop then blocking answer."""
    trace = run_with_trace(body.q, body.history)
    return {
        "answer": trace.answer,
        "search_calls": [
            {
                "query": c.query,
                "collection": c.collection,
                "hits": c.hits,
            }
            for c in trace.search_calls
        ],
        "context": trace.all_context,
    }


@app.post("/agent/stream")
def agent_stream_endpoint(body: AgentQuery):
    """Agentic RAG — SearchingExpert loop then SSE token stream."""

    def _sse_tokens():
        for token in agent_stream(body.q, body.history):
            if token.startswith(_CONTEXT_SENTINEL):
                ctx = json.loads(token[len(_CONTEXT_SENTINEL) :])
                yield f"data: {json.dumps({'context': ctx})}\n\n"
            else:
                yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse_tokens(), media_type="text/event-stream")


@app.post("/feedback")
def feedback(body: Feedback):
    entry = {
        "id": f"s_{int(time.time())}",
        "type": "sentence",
        "query": body.query,
        "kodava": body.correction or body.answer,
        "status": body.status,
        "source": "ui_feedback",
    }

    try:
        if body.status in ("approved", "corrected"):
            append_corpus_entry("corpus/sentences.jsonl", entry)
            invalidate("sentences")
            return {"saved": True, "collection": "sentences"}

        elif body.status == "rejected":
            append_corpus_entry("corpus/review.jsonl", entry)
            return {"saved": True, "collection": "review"}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"saved": False, "error": "unknown status"}


@app.get("/review")
def get_review():
    path = CORPUS / "review.jsonl"
    if not path.exists():
        return {"items": []}
    items = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {"items": items, "count": len(items)}


@app.get("/health")
def health():
    return {"ok": True}
