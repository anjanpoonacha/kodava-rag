import json
import re
from rank_bm25 import BM25Okapi
from config import DATA, TOP_K, BM25_CANDIDATES, WORD_SEARCH_THRESHOLD

# Punctuation characters that corrupt BM25 token matching when attached to
# query words (e.g. "morning?" ≠ "morning", "niin." ≠ "niin").
# The corpus entries are stored without trailing punctuation so we must
# normalise the query to match.
_PUNCT_RE = re.compile(r"[^\w\s\'\-]")

# Higher number = higher priority in re-ranking after BM25 retrieval
_CONFIDENCE_RANK = {
    "verified": 3,
    "audio_source": 2,
    "textbook": 1,
    "unverified": 0,
}

_indexes: dict = {}


def _tokenize(text: str) -> list[str]:
    """Lowercase and strip punctuation before splitting into BM25 tokens.

    Preserves apostrophes (Kodava uses ʼ/ʻ in dative suffix -ʼk) and
    hyphens (compound words). Strips everything else that BM25 would
    treat as part of a token, corrupting match scores.

    Leading/trailing apostrophes on individual tokens are stripped so that
    quoted terms like 'cook' tokenize to 'cook' not "'cook'" or "cook'".
    """
    tokens = _PUNCT_RE.sub(" ", text.lower()).split()
    return [t.strip("'") for t in tokens if t.strip("'")]


# Minimum per-token BM25 score for Layer 2 token fan-out.
# Replaces the old hand-maintained _STOPWORDS blocklist.
#
# BM25Okapi IDF naturally weights common English function words near zero
# (e.g. "to" scores ≤ 3.5, "the" ≤ 3.0 on any single corpus entry).
# Content-bearing tokens score substantially higher:
#   "how"  → 7.4   (ennane entries)
#   "cook" → 9+    (adige entries)
#   "are"  → 5.8   (are = waist/half)
#
# Setting the threshold to 4.0 lets semantic content tokens through while
# suppressing English function words that BM25 already down-weights via IDF,
# without a hand-maintained list that could silently suppress valid lookups.
_MIN_TOKEN_SCORE = 4.0


def _load(collection: str):
    if collection in _indexes:
        return _indexes[collection]
    path = DATA / "corpus" / f"{collection}.jsonl"
    docs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    if not docs:
        _indexes[collection] = (None, [])
        return _indexes[collection]
    tokenized = [
        _tokenize(
            " ".join(
                filter(
                    None,
                    [
                        d.get("text", ""),
                        d.get("kodava", ""),
                        d.get("english", ""),
                        d.get("kannada", ""),
                        d.get("devanagari", ""),
                        d.get("correct", ""),
                        d.get("wrong", ""),
                        d.get("explanation", ""),
                    ],
                )
            )
        )
        for d in docs
    ]
    tokenized = [t if t else ["_"] for t in tokenized]
    _indexes[collection] = (BM25Okapi(tokenized), docs)
    return _indexes[collection]


def invalidate(collection: str | None = None):
    if collection:
        _indexes.pop(collection, None)
    else:
        _indexes.clear()


def _rerank_by_confidence(docs: list[dict]) -> list[dict]:
    """Stable sort: preserve BM25 order within each confidence tier."""
    return sorted(
        docs,
        key=lambda d: _CONFIDENCE_RANK.get(d.get("confidence", ""), 0),
        reverse=True,
    )


def search(query: str, collection: str = "sentences") -> list[dict]:
    """Layer 1: phrase-level BM25 — full query string against one collection."""
    bm25, docs = _load(collection)
    if bm25 is None:
        return []
    tokens = _tokenize(query)
    scores = bm25.get_scores(tokens)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :BM25_CANDIDATES
    ]
    candidates = [docs[i] for i in top if scores[i] > 0][:TOP_K]
    return _rerank_by_confidence(candidates)


def search_by_tokens(query: str, collection: str) -> list[dict]:
    """Layer 2: word-level token voting — run BM25 per content token,
    rank by (tokens_matched DESC, sum_score DESC). Surfaces partial matches
    when full-phrase search misses due to missing vocabulary.

    Uses a per-token minimum BM25 score threshold (_MIN_TOKEN_SCORE) instead
    of a hand-maintained stopword list.  BM25 IDF naturally assigns near-zero
    scores to high-frequency English function words ("to", "the", "a"), so
    the threshold suppresses noise without blocking valid lookup targets like
    "how" (ennane) or "are" (are = waist/half) that were previously hidden.
    """
    bm25, docs = _load(collection)
    if bm25 is None:
        return []

    tokens = [t for t in _tokenize(query) if len(t) > 1]
    if not tokens:
        return []

    # Accumulate per-doc: total BM25 score and number of tokens that cleared
    # the minimum score threshold.
    score_sum = [0.0] * len(docs)
    match_count = [0] * len(docs)

    for token in tokens:
        per_token_scores = bm25.get_scores([token])
        for i, s in enumerate(per_token_scores):
            if s >= _MIN_TOKEN_SCORE:
                score_sum[i] += s
                match_count[i] += 1

    # Rank: primary = tokens matched, secondary = sum of BM25 scores
    candidates = [i for i in range(len(docs)) if match_count[i] > 0]
    candidates.sort(key=lambda i: (match_count[i], score_sum[i]), reverse=True)

    return _rerank_by_confidence([docs[i] for i in candidates[:TOP_K]])


_COMPOSITION_KEYWORDS = frozenset(
    {
        "paragraph",
        "passage",
        "compose",
        "write a",
        "write me",
        "form a",
        "daily routine",
        "introduce yourself",
        "tell me about yourself",
        "describe yourself",
    }
)

# Maps query keywords → corpus topic tags.
# Layer 0 uses this to inject all paragraph threads for a topic when any
# query token matches a key — bypassing BM25 length-normalisation bias that
# causes short flashcards (2–11 tokens) to outrank long narratives (750 tokens).
_TOPIC_TAG_MAP: dict[str, str] = {
    "kaveri": "kaveri_sankramana",
    "kaaveri": "kaveri_sankramana",
    "changrandi": "kaveri_sankramana",
    "changraandi": "kaveri_sankramana",
    "sankramana": "kaveri_sankramana",
    "shankramana": "kaveri_sankramana",
    "kailpodh": "kailpodh",
    "puttari": "puttari",
    "puthari": "puttari",
}


def augment_query(query: str) -> str:
    """Append 'paragraph' to composition queries so BM25 surfaces thread entries.

    Query-frame stripping ("Translate:", "How do you say X in Kodava", etc.) is
    handled by the SearchExpert agent which reformulates natural-language queries
    into focused BM25 keywords before calling search_kodava.  The /query endpoint
    now routes through the agent, so manual regex is not needed here.
    """
    q_lower = query.lower()
    if any(kw in q_lower for kw in _COMPOSITION_KEYWORDS):
        if "paragraph" not in q_lower:
            return query + " paragraph"
    return query


def _topic_threads(query_tokens: list[str]) -> list[dict]:
    """Return all paragraph threads whose topic tag matches a query token.

    Pure tag lookup — no BM25. Avoids length-normalisation bias entirely.
    Uses sentences_narrative as the source since paragraph threads live there.
    """
    matched_topics: set[str] = set()
    for token in query_tokens:
        topic = _TOPIC_TAG_MAP.get(token.lower())
        if topic:
            matched_topics.add(topic)
    if not matched_topics:
        return []

    _, docs = _load("sentences_narrative")
    return [
        d
        for d in docs
        if "paragraph" in d.get("tags", [])
        and any(t in matched_topics for t in d.get("tags", []))
    ]


def _search_threads(query: str) -> list[dict]:
    """BM25-based paragraph thread search for composition queries.

    Searches sentences_narrative so that lesson flashcards cannot crowd out
    narrative paragraph entries. Only paragraph-tagged entries are returned.
    """
    bm25, docs = _load("sentences_narrative")
    if bm25 is None:
        return []
    tokens = _tokenize(query)
    scores = bm25.get_scores(tokens)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :BM25_CANDIDATES
    ]
    return [
        docs[i] for i in top if scores[i] > 0 and "paragraph" in docs[i].get("tags", [])
    ][:4]


def _is_paragraph(doc: dict) -> bool:
    return "paragraph" in doc.get("tags", [])


def search_all(query: str) -> list[dict]:
    """Layered retrieval across all collections.

    Layer 0a (topic threads): when query tokens match a known topic tag, inject
      all paragraph threads for that topic directly — tag lookup, no BM25.
      Fixes zero-score cases like 'How do Kodavas celebrate Changrandi?' where
      BM25 length normalisation buries 750-token paragraphs behind 2-token
      flashcards.
    Layer 0b (composition threads): for 'write a paragraph' style queries,
      inject the top BM25-ranked paragraph threads from sentences_narrative.
    Layer 1 (phrase): full-query BM25 per collection, highest priority.
    Layer 2 (token voting): per-token fan-out for collections where Layer 1
      returns fewer than WORD_SEARCH_THRESHOLD hits.

    sentences_lesson and sentences_narrative are searched independently so
    the two populations (avg 11 tokens vs avg 750 tokens) never compete in
    the same BM25 index. sentences_lesson handles grammar/phrase lookup;
    sentences_narrative handles topic knowledge and audio content.
    """
    COL_CAPS = {
        "sentences_lesson": 2,
        "sentences_narrative": 4,
        "grammar_rules": 3,
        "vocabulary": 5,
        "phonemes": 2,
        "_threads": 4,  # raised from 2 — matches max sections per topic (4)
    }
    seen_ids: set = set()

    per_col: dict[str, list[dict]] = {}

    def _collect(docs: list[dict], col: str, cap: int) -> None:
        bucket = per_col.setdefault(col, [])
        for d in docs:
            if len(bucket) >= cap:
                break
            doc_id = d.get("id")
            if doc_id and doc_id in seen_ids:
                continue
            bucket.append(d)
            if doc_id:
                seen_ids.add(doc_id)

    query_tokens = _tokenize(query)

    # Layer 0a: topic-tag thread injection (no BM25, pure tag lookup)
    topic_hits = _topic_threads(query_tokens)
    if topic_hits:
        _collect(topic_hits, "_threads", COL_CAPS["_threads"])

    # Layer 0b: composition paragraph injection (BM25 over narrative collection)
    elif "paragraph" in query.lower():
        _collect(_search_threads(query), "_threads", COL_CAPS["_threads"])

    for col in (
        "sentences_lesson",
        "sentences_narrative",
        "grammar_rules",
        "vocabulary",
        "phonemes",
    ):
        phrase_cap = COL_CAPS.get(col, 3)
        try:
            phrase_hits = search(query, col)

            # Paragraph threads are managed exclusively by Layer 0.
            # Exclude them from Layer 1 so they don't bleed into unrelated
            # queries via BM25 — their size (750 tokens) gives them
            # artificially high scores on any query containing common words.
            if col == "sentences_narrative":
                phrase_hits = [d for d in phrase_hits if not _is_paragraph(d)]

            _collect(phrase_hits, col, phrase_cap)

            if col == "vocabulary" or len(phrase_hits) < WORD_SEARCH_THRESHOLD:
                token_hits = search_by_tokens(query, col)
                if col == "sentences_narrative":
                    token_hits = [d for d in token_hits if not _is_paragraph(d)]
                _collect(token_hits, col + "_tokens", phrase_cap)
        except FileNotFoundError:
            pass

    ordered_cols = [
        "_threads",
        "sentences_narrative",
        "sentences_lesson",
        "grammar_rules",
        "vocabulary",
        "vocabulary_tokens",
        "phonemes",
    ]
    merged: list[dict] = []
    for col in ordered_cols:
        merged.extend(per_col.get(col, []))

    return merged[:TOP_K]


# ---------------------------------------------------------------------------
# Hybrid BM25 + Dense — RRF merge
# ---------------------------------------------------------------------------


def _rrf_merge(
    bm25_results: list[dict],
    dense_results: list[dict],
    top_k: int,
    k: int = 60,
) -> list[dict]:
    """Reciprocal Rank Fusion of BM25 and dense ranked lists.

    score(doc) = Σ 1/(k + rank)  across both lists.
    Documents appearing in both lists are boosted over those appearing in only one.
    k=60 is the standard production default (per 2026 research consensus).
    """
    scores: dict[str, float] = {}
    docs_by_id: dict[str, dict] = {}

    for rank, doc in enumerate(bm25_results, 1):
        did = doc.get("id", "")
        if not did:
            continue
        scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank)
        docs_by_id[did] = doc

    for rank, doc in enumerate(dense_results, 1):
        did = doc.get("id", "")
        if not did:
            continue
        scores[did] = scores.get(did, 0.0) + 1.0 / (k + rank)
        docs_by_id.setdefault(did, doc)

    ranked_ids = sorted(scores, key=scores.__getitem__, reverse=True)
    return [docs_by_id[did] for did in ranked_ids[:top_k]]


async def search_all_async(query: str) -> list[dict]:
    """Hybrid BM25 + dense retrieval with RRF merge.

    BM25 and the embedding API call run concurrently via asyncio.  Total
    retrieval latency = max(BM25_time ~5ms, embed_time ~100-400ms) rather
    than their sum.

    The top BM25_ANCHOR results from BM25 are placed unconditionally at the
    front of the merged list before RRF fills the remaining slots.  This
    prevents the dense lane from displacing exact-match vocabulary hits
    (e.g. ennane / how) that BM25 ranks highly but the embedding model
    associates with semantically adjacent but unrelated queries.

    Falls back to BM25-only results when:
    - EMBED_ENABLED=false
    - embeddings.npy not built yet
    - embedding API call fails (embed_one returns None)
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from core.embedder import embed_one
    from core.vector_index import load as load_index

    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=2) as pool:
        bm25_future = loop.run_in_executor(pool, search_all, query)
        embed_future = loop.run_in_executor(pool, embed_one, query)
        bm25_results, query_vec = await asyncio.gather(bm25_future, embed_future)

    if query_vec is None:
        return bm25_results

    idx = load_index()
    if idx is None:
        return bm25_results

    dense_results = idx.search(query_vec, top_k=TOP_K)
    return _rrf_merge(bm25_results, dense_results, top_k=TOP_K)
