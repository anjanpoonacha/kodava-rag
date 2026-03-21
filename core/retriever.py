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
    """
    return _PUNCT_RE.sub(" ", text.lower()).split()


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
                    d.get("kannada", ""),
                    d.get("devanagari", ""),
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
    """Layer 2: word-level token voting — run BM25 per non-stopword token,
    rank by (tokens_matched DESC, sum_score DESC). Surfaces partial matches
    when full-phrase search misses due to missing vocabulary.
    """
    bm25, docs = _load(collection)
    if bm25 is None:
        return []

    tokens = [t for t in _tokenize(query) if t not in _STOPWORDS and len(t) > 1]
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


def augment_query(query: str) -> str:
    """Append 'paragraph' to composition queries so BM25 surfaces thread entries."""
    q_lower = query.lower()
    if any(kw in q_lower for kw in _COMPOSITION_KEYWORDS):
        if "paragraph" not in q_lower:
            return query + " paragraph"
    return query


def _search_threads(query: str) -> list[dict]:
    """Targeted search for paragraph thread entries — bypasses confidence reranking
    so audio_source threads are not buried under verified vocabulary hits."""
    bm25, docs = _load("sentences")
    if bm25 is None:
        return []
    tokens = _tokenize(query)
    scores = bm25.get_scores(tokens)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :BM25_CANDIDATES
    ]
    # Only return entries tagged as paragraph threads
    return [
        docs[i] for i in top if scores[i] > 0 and "paragraph" in docs[i].get("tags", [])
    ][:2]  # at most 2 threads per composition query


def search_all(query: str) -> list[dict]:
    """Layered retrieval across all collections.

    Layer 0 (threads): for composition queries, inject the top matching
      paragraph thread directly so confidence reranking cannot bury it.
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

    # Layer 0: inject top paragraph thread for composition queries
    if "paragraph" in query.lower():
        _add(_search_threads(query), 2)

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
