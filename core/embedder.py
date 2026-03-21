"""Dense embedding via OpenAI-compatible LiteLLM proxy.

Modes (controlled by EMBED_ENABLED in config):
  "true"  — real embeddings via SAP AI Core LiteLLM endpoint
  "local" — deterministic random-projection embeddings, no API calls,
             reproducible across runs (same text → same vector), used for
             local development and testing without network access
  "false" — embedder is disabled; embed_one returns None

Public API
----------
embed_one(text)          → np.ndarray | None   (LRU-cached, used per query)
embed_batch(texts)       → np.ndarray           (used by build_corpus.py)
DIMS                     → int                  (embedding dimensions)
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

import numpy as np

from config import EMBED_ENABLED, EMBED_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL

logger = logging.getLogger(__name__)

DIMS = 3072  # gemini-embedding output dimensions (text-embedding-3-small: 1536)

# ---------------------------------------------------------------------------
# Local (no-API) deterministic projection — for local dev / CI
# ---------------------------------------------------------------------------

# Seed derived from model name so "local" embeddings are stable across builds
# but distinct per model.  The projection is random but reproducible.
_LOCAL_SEED = int(hashlib.sha256(EMBED_MODEL.encode()).hexdigest()[:8], 16) & 0xFFFFFFFF
_rng = np.random.default_rng(_LOCAL_SEED)
_PROJ: np.ndarray | None = None  # lazy — built on first use


def _local_projection() -> np.ndarray:
    """Return (4096, DIMS) random Gaussian projection matrix, built once.

    Re-built automatically when DIMS changes (different model default).
    """
    global _PROJ
    if _PROJ is None or _PROJ.shape[1] != DIMS:
        _PROJ = _rng.standard_normal((4096, DIMS)).astype(np.float32)
    return _PROJ


def _local_embed(text: str) -> np.ndarray:
    """Deterministic local embedding via character-level bag-of-bigrams projection.

    Not semantic — purely for local smoke-testing the pipeline plumbing.
    Same text always produces the same vector regardless of process restart.
    """
    proj = _local_projection()
    text = text.lower()[:2048]
    # Build a sparse bigram frequency vector over 4096 buckets
    bow = np.zeros(4096, dtype=np.float32)
    for i in range(len(text) - 1):
        bigram = text[i : i + 2]
        bucket = int(hashlib.md5(bigram.encode()).hexdigest()[:4], 16) % 4096
        bow[bucket] += 1.0
    if bow.sum() > 0:
        bow /= bow.sum()
    vec = bow @ proj  # (4096,) × (4096, DIMS) → (DIMS,)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ---------------------------------------------------------------------------
# Remote embedding via LiteLLM (openai-compatible)
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from openai import OpenAI  # type: ignore[import]

            _client = OpenAI(
                api_key=LITELLM_API_KEY,
                base_url=LITELLM_BASE_URL,
            )
        except ImportError:
            logger.warning("openai package not installed — dense retrieval disabled")
    return _client


def _remote_embed_batch(texts: list[str]) -> np.ndarray:
    """Call the LiteLLM embeddings endpoint for a batch of texts."""
    client = _get_client()
    if client is None:
        raise RuntimeError("openai client unavailable")
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    vecs = [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
    return np.array(vecs, dtype=np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def embed_one(text: str) -> np.ndarray | None:
    """Embed a single query string.  Results are LRU-cached (maxsize=256).

    Cache key is the text itself (lru_cache hashes by argument equality).
    Returns None when EMBED_ENABLED=false so callers can skip the dense lane.
    """
    if EMBED_ENABLED == "false":
        return None
    if EMBED_ENABLED == "local":
        return _local_embed(text)
    try:
        vecs = _remote_embed_batch([text])
        return vecs[0]
    except Exception as exc:
        logger.warning("embed_one failed (%s) — dense lane skipped for this query", exc)
        return None


def embed_batch(texts: list[str], batch_size: int = 200) -> np.ndarray:
    """Embed a list of texts in chunks.  Used by build_corpus.py.

    Returns (N, DIMS) float32 array.  Raises on API failure so the build
    step fails loudly rather than silently producing a partial index.
    """
    if EMBED_ENABLED == "false":
        raise RuntimeError("EMBED_ENABLED=false — cannot embed batch")

    all_vecs: list[np.ndarray] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        chunk = texts[start : start + batch_size]
        end = min(start + batch_size, total)
        logger.info("embedding %d/%d", end, total)
        print(f"  embedding {end}/{total}...")
        if EMBED_ENABLED == "local":
            vecs = np.array([_local_embed(t) for t in chunk], dtype=np.float32)
        else:
            vecs = _remote_embed_batch(chunk)
        all_vecs.append(vecs)

    return np.vstack(all_vecs)
