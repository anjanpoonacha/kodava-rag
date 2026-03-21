#!/usr/bin/env python3
"""Factory — updates the thakk submodule, then walks data/thakk/ and writes corpus JSONL."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA
from core.github_sync import sync_source_files
import ingesters.corpus_jsonl  # noqa: F401 — registers CorpusJsonlIngester (thakk/corpus)
import ingesters.vocab_table  # noqa: F401 — registers VocabTableIngester
import ingesters.corrections  # noqa: F401 — registers CorrectionsIngester
import ingesters.phoneme_map  # noqa: F401 — registers PhonemeMapIngester
import ingesters.elementary_kodava  # noqa: F401 — registers ElementaryKodavaIngester
import ingesters.training_data  # noqa: F401 — registers TrainingDataIngester

# TranscriptionIngester is NOT registered here — it runs on-demand via ingest_session.py
# and writes its output to data/thakk/corpus/sentences.jsonl (picked up by corpus_jsonl.py)
from ingesters import REGISTRY

THAKK = DATA / "thakk"  # git submodule — source of truth
CORPUS = DATA / "corpus"
CORPUS.mkdir(parents=True, exist_ok=True)

# Collections the factory writes — keyed by CorpusEntry.type
COLLECTIONS = {
    "vocabulary": CORPUS / "vocabulary.jsonl",
    "grammar_rule": CORPUS / "grammar_rules.jsonl",
    "phoneme": CORPUS / "phonemes.jsonl",
    "sentence": CORPUS / "sentences.jsonl",
}


def _load_existing_sentences() -> tuple[list[dict], set[str]]:
    """Load hand-verified sentences preserved across builds."""
    path = CORPUS / "sentences.jsonl"
    entries: list[dict] = []
    ids: set[str] = set()
    if not path.exists():
        return entries, ids
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if e.get("id") and e["id"] not in ids:
                ids.add(e["id"])
                entries.append(e)
        except json.JSONDecodeError:
            pass
    return entries, ids


def build():
    print("Updating thakk submodule...")
    sync_source_files()
    print("Building corpus...")

    seen: set[str] = set()

    # Preserve hand-verified sentences from previous build
    existing_sentences, _ = _load_existing_sentences()
    buckets: dict[str, list[dict]] = {k: [] for k in COLLECTIONS}
    for entry in existing_sentences:
        eid = entry.get("id")
        if eid and eid not in seen:
            buckets["sentence"].append(entry)
            seen.add(eid)

    warnings = 0

    def _ingest_path(path: Path) -> None:
        nonlocal warnings
        for ingester in REGISTRY:
            if not ingester.can_handle(path):
                continue
            for entry in ingester.ingest(path):
                if any("\u0900" <= ch <= "\u097f" for ch in entry.kodava):
                    print(
                        f"  WARN: Devanagari in kodava field — {path.name}: {entry.kodava[:40]}"
                    )
                    warnings += 1
                    continue
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                if entry.type in buckets:
                    buckets[entry.type].append(entry.to_dict())
            break  # only first matching ingester per file

    # Pass 1 — curated corpus JSONL first so they claim their IDs in `seen`
    # before any derived/audio-vocab sources can produce the same entry with
    # stale (empty) fields.
    for path in sorted((THAKK / "corpus").glob("*.jsonl")):
        if path.is_file():
            _ingest_path(path)

    # Pass 2 — all remaining thakk files (audio-vocab, textbook, training data)
    for path in sorted(THAKK.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.parent == THAKK / "corpus" and path.suffix == ".jsonl":
            continue  # already processed in pass 1
        _ingest_path(path)

    # Post-process: backfill empty explanation from english field so BM25 has
    # at least one English token to match against for every vocabulary entry.
    backfilled = 0
    for entry in buckets.get("vocabulary", []):
        if (
            not entry.get("explanation", "").strip()
            and entry.get("english", "").strip()
        ):
            entry["explanation"] = entry["english"]
            backfilled += 1
    if backfilled:
        print(f"  backfilled explanation from english: {backfilled} vocabulary entries")

    # Write all collections
    for col_type, out_path in COLLECTIONS.items():
        entries = buckets[col_type]
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {out_path.name}: {len(entries)}")

    # review.jsonl is never overwritten by the build
    review = CORPUS / "review.jsonl"
    if not review.exists():
        review.touch()

    count = sum(len(v) for v in buckets.values())
    print(f"  total: {count} entries, {warnings} warnings")
    if warnings:
        print(f"  WARNING: {warnings} entries skipped — fix source data")
    else:
        print("  OK: 0 errors")


if __name__ == "__main__":
    build()
