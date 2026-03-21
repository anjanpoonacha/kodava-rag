import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import DATA, PROMPT_FETCH, PROMPT_BRANCH, PROMPT_REPO
from core.github_sync import append_corpus_entry
from core.llm import SYSTEM, ask
from core.retriever import invalidate, search_all

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


class Feedback(BaseModel):
    query: str
    answer: str
    correction: str | None = None
    status: str  # "approved" | "corrected" | "rejected"


@app.post("/query")
def query(body: Query):
    context = search_all(body.q)
    answer = ask(body.q, context)
    return {"answer": answer, "context": context}


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
