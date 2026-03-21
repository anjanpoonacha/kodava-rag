"""In-memory cosine similarity index over embedded corpus documents.

Built from:
  data/corpus/embeddings.npy        — (N, DIMS) float32 matrix
  data/corpus/embeddings_meta.json  — [{id, collection, confidence}, …]

The index is loaded once at server startup and lives entirely in memory
(~20 MB for 3,332 docs × 1,536 dims).  No vector database required.

Public API
----------
load() -> VectorIndex | None
    Load from disk.  Returns None if files are missing (BM25-only fallback).
    Subsequent calls return the cached instance without re-reading disk.

invalidate()
    Clear the cached instance.  Called by build_corpus.py after re-embedding
    so the next load() picks up the freshly written files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from config import DATA, EMBED_ENABLED
from core.retriever import _rerank_by_confidence  # re-use existing confidence ranking

logger = logging.getLogger(__name__)

_EMBEDDINGS_NPY = DATA / "corpus" / "embeddings.npy"
_EMBEDDINGS_META = DATA / "corpus" / "embeddings_meta.json"

_instance: "VectorIndex | None" = None


class VectorIndex:
    """Cosine similarity search over a pre-computed embedding matrix."""

    def __init__(
        self, matrix: np.ndarray, meta: list[dict], docs_by_id: dict[str, dict]
    ):
        # Rows are L2-normalised so dot product == cosine similarity.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        self._matrix = (matrix / norms).astype(np.float32)
        self._meta = meta  # [{id, collection, confidence}, …]
        self._docs = docs_by_id  # id → full corpus doc dict

    def search(self, query_vec: np.ndarray, top_k: int = 12) -> list[dict]:
        """Return top_k docs by cosine similarity, re-ranked by confidence."""
        norm = np.linalg.norm(query_vec)
        if norm == 0:
            return []
        qv = (query_vec / norm).astype(np.float32)
        scores = self._matrix @ qv  # (N,) cosine similarities
        top_idx = np.argpartition(scores, -min(top_k * 2, len(scores)))[
            -min(top_k * 2, len(scores)) :
        ]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]][:top_k]

        results: list[dict] = []
        for i in top_idx:
            if scores[i] <= 0:
                continue
            doc_id = self._meta[i]["id"]
            doc = self._docs.get(doc_id)
            if doc:
                results.append(doc)

        return _rerank_by_confidence(results)


def _load_corpus_docs() -> dict[str, dict]:
    """Load all corpus JSONL collections into an id-keyed dict."""
    import json as _json

    docs: dict[str, dict] = {}
    corpus_dir = DATA / "corpus"
    for name in (
        "sentences_lesson.jsonl",
        "sentences_narrative.jsonl",
        "vocabulary.jsonl",
        "grammar_rules.jsonl",
        "phonemes.jsonl",
    ):
        path = corpus_dir / name
        if not path.exists():
            # Fall back to combined sentences.jsonl if split hasn't been generated yet
            if name in ("sentences_lesson.jsonl", "sentences_narrative.jsonl"):
                path = corpus_dir / "sentences.jsonl"
                if not path.exists():
                    continue
            else:
                continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = _json.loads(line)
                if doc.get("id"):
                    docs[doc["id"]] = doc
            except ValueError:
                pass
    return docs


def load() -> "VectorIndex | None":
    """Return the cached VectorIndex, loading from disk if needed.

    Returns None when:
    - EMBED_ENABLED=false
    - embeddings files don't exist yet (first run before build_corpus.py)
    - numpy/files are corrupt (logs warning, returns None gracefully)
    """
    global _instance
    if _instance is not None:
        return _instance

    if EMBED_ENABLED == "false":
        return None

    if not _EMBEDDINGS_NPY.exists() or not _EMBEDDINGS_META.exists():
        logger.info(
            "embeddings not found — dense retrieval disabled (run build_corpus.py)"
        )
        return None

    try:
        matrix = np.load(str(_EMBEDDINGS_NPY))
        meta = json.loads(_EMBEDDINGS_META.read_text(encoding="utf-8"))
        docs = meta.get("docs", [])
        corpus_docs = _load_corpus_docs()

        logger.info(
            "vector index loaded: %d docs, %d dims, model=%s",
            len(docs),
            matrix.shape[1] if matrix.ndim == 2 else 0,
            meta.get("model", "unknown"),
        )
        print(
            f"[vector_index] loaded {len(docs)} embeddings "
            f"({matrix.shape[1]}d, model={meta.get('model', '?')})"
        )
        _instance = VectorIndex(matrix, docs, corpus_docs)
        return _instance

    except Exception as exc:
        logger.warning(
            "failed to load vector index: %s — dense retrieval disabled", exc
        )
        return None


def invalidate() -> None:
    """Clear the cached index so the next load() re-reads from disk."""
    global _instance
    _instance = None
    logger.info("vector index invalidated")
