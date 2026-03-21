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


# English stopwords to skip during token-level fan-out.
# Includes query-frame words that appear in almost every vocabulary query
# ("kodava", "word", "say", "mean", "translate") and carry no discriminating
# signal — their presence would cause meta-words to outscore content tokens.
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
        # Query-frame words — high-frequency in user queries but zero
        # discriminating power for vocabulary lookup
        "kodava",
        "word",
        "say",
        "mean",
        "means",
        "translate",
        "translation",
        "how",
        "takk",
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

    Each collection is allocated its own independent slot budget so that a
    high-scoring but irrelevant collection (e.g. sentences matching common
    query words) cannot consume the entire TOP_K budget and starve
    vocabulary. Results are deduplicated by id and capped at TOP_K.
    """
    # Per-collection slot budgets. vocabulary gets more slots because word
    # lookup queries must surface specific lexical entries that may rank below
    # generic action-word patterns in the BM25 list.
    COL_CAPS = {
        "sentences": 3,
        "grammar_rules": 3,
        "vocabulary": 5,
        "phonemes": 2,
        "_threads": 2,
    }
    seen_ids: set = set()

    # Collect results per-collection independently before merging.
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

    # Layer 0: inject top paragraph thread for composition queries
    if "paragraph" in query.lower():
        _collect(_search_threads(query), "_threads", COL_CAPS["_threads"])

    for col in ("sentences", "grammar_rules", "vocabulary", "phonemes"):
        phrase_cap = COL_CAPS.get(col, 3)
        try:
            # Layer 1: phrase-level BM25
            phrase_hits = search(query, col)
            _collect(phrase_hits, col, phrase_cap)

            # Layer 2: token voting — always run for vocabulary so that
            # content-specific terms (e.g. "cook") can surface entries that
            # rank below the phrase-level cap due to competing generic patterns.
            # Token voting gets its own additive cap so it is never crowded out
            # by phrase hits that already filled the bucket.
            # For other collections, run only when phrase search is thin.
            if col == "vocabulary" or len(phrase_hits) < WORD_SEARCH_THRESHOLD:
                token_hits = search_by_tokens(query, col)
                token_cap = phrase_cap if col == "vocabulary" else phrase_cap
                _collect(token_hits, col + "_tokens", token_cap)
        except FileNotFoundError:
            pass

    # Merge: threads first, then interleave phrase hits and token hits so that
    # content-specific vocabulary entries (from token voting) are not pushed
    # beyond TOP_K by generic phrase matches from other collections.
    ordered_cols = [
        "_threads",
        "sentences",
        "grammar_rules",
        "vocabulary",
        "vocabulary_tokens",
        "phonemes",
    ]
    merged: list[dict] = []
    for col in ordered_cols:
        merged.extend(per_col.get(col, []))

    return merged[:TOP_K]
