import json
from rank_bm25 import BM25Okapi
from config import DATA, TOP_K, BM25_CANDIDATES

_indexes: dict = {}


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
                    d.get("text", ""),  # pre-built searchable field (grammar_rules)
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
    bm25, docs = _load(collection)
    if bm25 is None:
        return []
    tokens = query.lower().split()
    scores = bm25.get_scores(tokens)
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
        :BM25_CANDIDATES
    ]
    return [docs[i] for i in top if scores[i] > 0][:TOP_K]


def search_all(query: str) -> list[dict]:
    # sentences first — human-verified ground truth, highest priority
    # cap each collection at 3 so day names and other vocab get enough slots
    PER_COLLECTION = 3
    results = []
    for col in ("sentences", "grammar_rules", "vocabulary", "phonemes"):
        try:
            hits = search(query, col)
            results.extend(hits[:PER_COLLECTION])
        except FileNotFoundError:
            pass
    return results[:TOP_K]
