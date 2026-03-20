import json
import time
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from core.retriever import search_all, invalidate
from core.llm import ask
from config import DATA

app = FastAPI(title="Kodava RAG")

CORPUS = DATA / "corpus"


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

    if body.status in ("approved", "corrected"):
        path = CORPUS / "sentences.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        invalidate("sentences")
        return {"saved": True, "collection": "sentences"}

    elif body.status == "rejected":
        path = CORPUS / "review.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"saved": True, "collection": "review"}

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
