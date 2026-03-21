#!/usr/bin/env python3
"""Factory — syncs source files from thakk, then walks data/processed/ and writes corpus JSONL."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA
from core.github_sync import sync_source_files
import ingesters.vocab_table  # noqa: F401 — registers VocabTableIngester
import ingesters.corrections  # noqa: F401 — registers CorrectionsIngester
import ingesters.phoneme_map  # noqa: F401 — registers PhonemeMapIngester
import ingesters.elementary_kodava  # noqa: F401 — registers ElementaryKodavaIngester
import ingesters.training_data  # noqa: F401 — registers TrainingDataIngester
from ingesters import REGISTRY

PROCESSED = DATA / "processed"
SEEDS = DATA / "seeds"
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
    """Load hand-verified sentences from sentences.jsonl — preserved across builds."""
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


def _load_seeds() -> tuple[list[dict], set[str]]:
    """Load hand-authored seed entries from data/seeds/*.jsonl.

    Seeds are always included in the corpus and take priority over ingested
    entries with the same id. They are the canonical source for derivation
    examples and other curated content that must not be overwritten by ingestion.
    """
    entries: list[dict] = []
    ids: set[str] = set()
    if not SEEDS.exists():
        return entries, ids
    for path in sorted(SEEDS.glob("*.jsonl")):
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
    print("Syncing source files from anjanpoonacha/thakk...")
    sync_source_files()
    print("Building corpus...")

    # Seed sentences bucket with existing hand-verified entries so they are
    # never dropped — textbook-derived sentences are added after deduplication.
    existing_sentences, seen = _load_existing_sentences()

    # Load hand-authored seeds (derivation examples, curated entries)
    seed_entries, seed_ids = _load_seeds()
    seen.update(seed_ids)
    print(f"  seeds: {len(seed_entries)} entries loaded from data/seeds/")

    buckets: dict[str, list[dict]] = {k: [] for k in COLLECTIONS}
    buckets["sentence"].extend(existing_sentences)
    # Distribute seeds into their respective collection buckets
    for entry in seed_entries:
        col_type = entry.get("type", "")
        if col_type in buckets:
            buckets[col_type].append(entry)

    warnings = 0

    for path in sorted(PROCESSED.rglob("*")):
        if not path.is_file():
            continue
        for ingester in REGISTRY:
            if not ingester.can_handle(path):
                continue
            entries = ingester.ingest(path)
            for entry in entries:
                # Validation: kodava must be romanized (no Devanagari)
                if any("\u0900" <= ch <= "\u097f" for ch in entry.kodava):
                    print(
                        f"  WARN: Devanagari in kodava field — {path.name}: {entry.kodava[:40]}"
                    )
                    warnings += 1
                    continue

                # Deduplication by deterministic id
                if entry.id in seen:
                    continue
                seen.add(entry.id)

                if entry.type in buckets:
                    buckets[entry.type].append(entry.to_dict())
            break  # only first matching ingester per file

    # Write all collections (sentences.jsonl now written, not just preserved)
    for col_type, out_path in COLLECTIONS.items():
        entries = buckets[col_type]
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {out_path.name}: {len(entries)}")

    # Preserve review.jsonl — never overwritten by the build
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
