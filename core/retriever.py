import json
from rank_bm25 import BM25Okapi
from config import DATA, TOP_K, BM25_CANDIDATES, WORD_SEARCH_THRESHOLD

_indexes: dict = {}

# English stopwords to skip during token-level fan-out
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "about",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "what",
        "which",
        "who",
        "this",
        "that",
    }
)


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
        " ".join(
            filter(
                None,
                [
                    d.get("text", ""),
                    d.get("kodava", ""),
                    d.get("english", ""),
                    d.get("correct", ""),
                    d.get("wrong", ""),
                    d.get("explanation", ""),
                ],
            )
        )
        .lower()
        .split()
        for d in docs
    ]
    tokenized = [t if t else ["_"] for t in tokenized]
    _indexes[collection] = (BM25Okapi(tokenized), docs)
    return _indexes[collection]


def invalidate(collection: str = None):
    if collection:
        _indexes.pop(collection, None)
    else:
        _indexes.clear()


def search(query: str, collection: str = "sentences") -> list[dict]:
    """Layer 1: phrase-level BM25 — full query string against one collection."""
    bm25, docs = _load(collection)
    if bm25 is None:
        return []
    tokens = query.lower().split()
    scores = bm25.get_scores(tokens)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :BM25_CANDIDATES
    ]
    return [docs[i] for i in top if scores[i] > 0][:TOP_K]


def search_by_tokens(query: str, collection: str) -> list[dict]:
    """Layer 2: word-level token voting — run BM25 per non-stopword token,
    rank by (tokens_matched DESC, sum_score DESC). Surfaces partial matches
    when full-phrase search misses due to missing vocabulary.
    """
    bm25, docs = _load(collection)
    if bm25 is None:
        return []

    tokens = [t for t in query.lower().split() if t not in _STOPWORDS and len(t) > 1]
    if not tokens:
        return []

    # Accumulate per-doc: total BM25 score and number of tokens matched
    score_sum = [0.0] * len(docs)
    match_count = [0] * len(docs)

    for token in tokens:
        per_token_scores = bm25.get_scores([token])
        for i, s in enumerate(per_token_scores):
            if s > 0:
                score_sum[i] += s
                match_count[i] += 1

    # Rank: primary = tokens matched, secondary = sum of BM25 scores
    candidates = [i for i in range(len(docs)) if match_count[i] > 0]
    candidates.sort(key=lambda i: (match_count[i], score_sum[i]), reverse=True)

    return [docs[i] for i in candidates[:TOP_K]]


def search_all(query: str) -> list[dict]:
    """Layered retrieval across all collections.

    Layer 1 (phrase): full-query BM25 per collection, highest priority.
    Layer 2 (token voting): per-token fan-out for collections where Layer 1
      returns fewer than WORD_SEARCH_THRESHOLD hits.
    Results are deduplicated by id and capped at TOP_K.
    """
    PER_COLLECTION = 3
    seen_ids: set = set()
    results: list[dict] = []

    def _add(docs: list[dict], cap: int):
        added = 0
        for d in docs:
            if added >= cap:
                break
            doc_id = d.get("id")
            if doc_id and doc_id in seen_ids:
                continue
            results.append(d)
            if doc_id:
                seen_ids.add(doc_id)
            added += 1

    for col in ("sentences", "grammar_rules", "vocabulary", "phonemes"):
        try:
            # Layer 1
            phrase_hits = search(query, col)
            _add(phrase_hits, PER_COLLECTION)

            # Layer 2: token voting fallback when phrase search is thin
            if len(phrase_hits) < WORD_SEARCH_THRESHOLD:
                token_hits = search_by_tokens(query, col)
                _add(token_hits, PER_COLLECTION)
        except FileNotFoundError:
            pass

    return results[:TOP_K]
