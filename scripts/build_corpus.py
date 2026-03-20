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
from ingesters import REGISTRY

PROCESSED = DATA / "processed"
CORPUS = DATA / "corpus"
CORPUS.mkdir(parents=True, exist_ok=True)

# Collections the factory writes — keyed by CorpusEntry.type
COLLECTIONS = {
    "vocabulary": CORPUS / "vocabulary.jsonl",
    "grammar_rule": CORPUS / "grammar_rules.jsonl",
    "phoneme": CORPUS / "phonemes.jsonl",
}


def build():
    print("Syncing source files from anjanpoonacha/thakk...")
    sync_source_files()
    print("Building corpus...")
    buckets: dict[str, list[dict]] = {k: [] for k in COLLECTIONS}
    seen: set[str] = set()
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

    # Write collections
    for col_type, out_path in COLLECTIONS.items():
        entries = buckets[col_type]
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"  {out_path.name}: {len(entries)}")

    # Preserve sentences.jsonl and review.jsonl — never overwritten
    for name in ("sentences.jsonl", "review.jsonl"):
        p = CORPUS / name
        if not p.exists():
            p.touch()

    count = sum(len(v) for v in buckets.values())
    print(f"  total: {count} entries, {warnings} warnings")
    if warnings:
        print(f"  WARNING: {warnings} entries skipped — fix source data")
    else:
        print("  OK: 0 errors")


if __name__ == "__main__":
    build()
