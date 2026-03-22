import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    ADMIN_TOKEN,
    REBUILD_TOKEN,
    DATA,
    PROMPT_FETCH,
    PROMPT_BRANCH,
    PROMPT_REPO,
)
from config import FEEDBACK_MOCK
from core.agent import run_with_trace
from core.agent import stream as agent_stream, _CONTEXT_SENTINEL
from core.github_sync import append_to_staging, ensure_open_pr
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
    load_vector_index()

    # Bootstrap local analytics file
    rejected_path = CORPUS / "rejected.jsonl"
    if not rejected_path.exists():
        rejected_path.touch()

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
    script: str | None = None  # roman | kannada | devanagari | all


class Feedback(BaseModel):
    query: str
    answer: str
    correction: str | None = None
    correction_type: str | None = None  # kodava | kannada | grammar | other
    status: str  # approved | corrected | rejected


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
        for token in agent_stream(body.q, body.history, body.script):
            if token.startswith(_CONTEXT_SENTINEL):
                ctx = json.loads(token[len(_CONTEXT_SENTINEL) :])
                yield f"data: {json.dumps({'context': ctx})}\n\n"
            else:
                yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse_tokens(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Feedback — staging pipeline
# ---------------------------------------------------------------------------


def _feedback_id(kodava: str, english: str) -> str:
    """Content-hash ID matching CorpusEntry.id for dedup."""
    key = f"sentence:{kodava.lower().strip()}:{english.lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _is_duplicate(entry_id: str) -> bool:
    """Check whether this ID already exists in the built corpus or pending staging."""
    for name in (
        "sentences.jsonl",
        "sentences_lesson.jsonl",
        "sentences_narrative.jsonl",
        "feedback_pending.jsonl",
    ):
        path = CORPUS / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                if json.loads(line).get("id") == entry_id:
                    return True
            except (json.JSONDecodeError, ValueError):
                continue
    return False


@app.post("/feedback")
def feedback(body: Feedback):
    # ── Rejected → local analytics file, no GitHub write ──
    if body.status == "rejected":
        entry = {
            "query": body.query,
            "answer": body.answer[:200],
            "status": "rejected",
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }
        path = CORPUS / "rejected.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"saved": True}

    # ── Approved or corrected → stage on feedback branch ──
    kodava = ""
    if body.status == "corrected" and body.correction_type == "kodava":
        kodava = (body.correction or "").strip()

    english = body.query.strip()
    entry_id = _feedback_id(kodava, english) if kodava else f"fb_{int(time.time())}"

    if kodava and _is_duplicate(entry_id):
        return {"saved": False, "duplicate": True, "message": "already in corpus"}

    # Truncate LLM answer for storage — full response isn't needed for review
    answer_summary = body.answer.replace("\n", " ")[:200].strip()

    ctype = body.correction_type
    explanation_parts = [f"User {body.status}"]
    if ctype:
        explanation_parts.append(f"[{ctype}]")
    if body.correction:
        explanation_parts.append(f": {body.correction[:120]}")
    explanation_parts.append(f". Original answer: {answer_summary[:120]}")

    entry = {
        "id": entry_id,
        "user_action": body.status,
        "correction_type": ctype,
        "query": body.query,
        "original_answer": answer_summary,
        "correction": body.correction,
        "kodava": kodava,
        "english": english,
        "explanation": "".join(explanation_parts),
        "tags": ["feedback", body.status] + ([ctype] if ctype else []),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    try:
        append_to_staging(entry)
        pr_url = ensure_open_pr()
        return {"saved": True, "pr_url": pr_url}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/review")
def get_review():
    """Return info about the open feedback PR (or local mock equivalent)."""
    if FEEDBACK_MOCK:
        pending = CORPUS / "feedback_pending.jsonl"
        count = 0
        if pending.exists():
            count = sum(1 for ln in pending.read_text().splitlines() if ln.strip())
        if count:
            return {
                "pr_url": f"file://{pending}",
                "status": "mock",
                "pending_count": count,
            }
        return {"pr_url": None, "status": "none", "pending_count": 0}

    from core.github_sync import _api

    try:
        owner = "anjanpoonacha"
        prs = _api(f"pulls?state=open&head={owner}:feedback/pending&base=main")
        if isinstance(prs, list) and prs:
            pr = prs[0]
            return {
                "pr_url": pr["html_url"],
                "status": "open",
                "title": pr.get("title", ""),
            }
    except Exception:
        pass

    return {"pr_url": None, "status": "none"}


# ---------------------------------------------------------------------------
# Admin — rebuild without redeploying
# ---------------------------------------------------------------------------


def _check_admin(authorization: str | None) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if authorization.removeprefix("Bearer ").strip() != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")


class RebuildRequest(BaseModel):
    token: str


@app.post("/admin/rebuild")
def admin_rebuild(
    body: RebuildRequest,
    authorization: str | None = Header(default=None),
):
    """Sync thakk + rebuild corpus + reload BM25 indexes.

    Requires ADMIN_TOKEN in the Authorization header (session auth)
    AND REBUILD_TOKEN in the request body (confirmation).
    """
    _check_admin(authorization)

    if not REBUILD_TOKEN:
        raise HTTPException(status_code=503, detail="REBUILD_TOKEN not configured")
    if body.token != REBUILD_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid rebuild token")

    from scripts.build_corpus import build

    try:
        build()
        invalidate()
        return {"ok": True, "message": "Corpus rebuilt and indexes reloaded"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/admin/status")
def admin_status(authorization: str | None = Header(default=None)):
    """Return corpus stats and pending feedback count. Validates the token."""
    _check_admin(authorization)

    stats: dict[str, int] = {}
    for name in ("vocabulary", "sentences", "grammar_rules", "phonemes"):
        path = CORPUS / f"{name}.jsonl"
        if path.exists():
            stats[name] = sum(1 for ln in path.read_text().splitlines() if ln.strip())

    pending = CORPUS / "feedback_pending.jsonl"
    pending_count = 0
    if pending.exists():
        pending_count = sum(1 for ln in pending.read_text().splitlines() if ln.strip())

    return {
        "pending_count": pending_count,
        "corpus": stats,
        "total": sum(stats.values()),
    }


@app.get("/admin")
def admin_page():
    admin_html = STATIC / "admin.html"
    if admin_html.exists():
        return FileResponse(str(admin_html))
    raise HTTPException(status_code=404, detail="Admin page not found")


@app.get("/health")
def health():
    return {"ok": True}
