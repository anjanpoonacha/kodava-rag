#!/usr/bin/env python3
"""Factory — updates the thakk submodule, then walks data/thakk/ and writes corpus JSONL."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA, EMBED_ENABLED, EMBED_MODEL
from core.github_sync import sync_source_files
import ingesters.corpus_jsonl  # noqa: F401 — registers CorpusJsonlIngester (thakk/corpus)
import ingesters.vocab_table  # noqa: F401 — registers VocabTableIngester
import ingesters.corrections  # noqa: F401 — registers CorrectionsIngester
import ingesters.phoneme_map  # noqa: F401 — registers PhonemeMapIngester
import ingesters.elementary_kodava  # noqa: F401 — registers ElementaryKodavaIngester
import ingesters.training_data  # noqa: F401 — registers TrainingDataIngester
import ingesters.verb_paradigm  # noqa: F401 — registers VerbParadigmIngester

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

# Derived sentence sub-collections written after the main build.
# Lesson Q&A flashcards (lesson:N tagged) live separately from narrative/audio
# content so BM25 length normalisation does not pit 2-token flashcards against
# 750-token transcription paragraphs in the same index.
SENTENCE_LESSON = CORPUS / "sentences_lesson.jsonl"
SENTENCE_NARRATIVE = CORPUS / "sentences_narrative.jsonl"


def _load_existing_sentences() -> tuple[list[dict], set[str]]:
    """Load hand-verified sentences preserved across builds.

    Excludes any entry whose ID already exists in data/thakk/corpus/sentences.jsonl
    so that edits to thakk-sourced sentences are not silently blocked by stale
    preserved copies in data/corpus/sentences.jsonl.
    """
    path = CORPUS / "sentences.jsonl"
    entries: list[dict] = []
    ids: set[str] = set()
    if not path.exists():
        return entries, ids

    # IDs that will be re-ingested from thakk — let thakk win
    thakk_ids: set[str] = set()
    thakk_sentences = THAKK / "corpus" / "sentences.jsonl"
    if thakk_sentences.exists():
        for line in thakk_sentences.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    thakk_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    pass

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            eid = e.get("id")
            if eid and eid not in ids and eid not in thakk_ids:
                ids.add(eid)
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

    # Post-process sentences: split into lesson flashcards vs narrative content.
    #
    # lesson:N tagged entries are short Q&A pairs (avg 11 tokens) from the
    # textbook. Narrative entries include audio transcription paragraphs (avg
    # 750 tokens) and individual transcription sentences. Keeping them in
    # separate BM25 indexes prevents short flashcards from outranking long
    # paragraphs via length-normalisation bias.
    sentences = buckets["sentence"]
    lesson_entries = [
        e for e in sentences if any(t.startswith("lesson:") for t in e.get("tags", []))
    ]
    narrative_entries = [
        e
        for e in sentences
        if not any(t.startswith("lesson:") for t in e.get("tags", []))
    ]
    for out_path, entries in (
        (SENTENCE_LESSON, lesson_entries),
        (SENTENCE_NARRATIVE, narrative_entries),
    ):
        with open(out_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        label = out_path.name
        print(f"  {label}: {len(entries)}")

    # rejected.jsonl is a local analytics file, never overwritten by the build
    rejected = CORPUS / "rejected.jsonl"
    if not rejected.exists():
        rejected.touch()

    count = sum(len(v) for v in buckets.values())
    print(f"  total: {count} entries, {warnings} warnings")
    if warnings:
        print(f"  WARNING: {warnings} entries skipped — fix source data")
    else:
        print("  OK: 0 errors")

    _embed_corpus()


def _corpus_hash() -> str:
    """SHA-256 of all embeddable collection files + embedding model name.

    Including the model name ensures that changing EMBED_MODEL invalidates
    any persisted embeddings.npy (e.g. on a PVC), preventing silent
    dimensionality mismatches.
    """
    h = hashlib.sha256()
    h.update(EMBED_MODEL.encode())
    for name in (
        "sentences_lesson.jsonl",
        "sentences_narrative.jsonl",
        "vocabulary.jsonl",
        "grammar_rules.jsonl",
        "phonemes.jsonl",
    ):
        p = CORPUS / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def _embed_corpus() -> None:
    """Embed all corpus documents and write embeddings.npy + embeddings_meta.json.

    Skips the embed step when:
    - EMBED_ENABLED=false
    - corpus content hash matches the hash stored from the last embed run

    Re-embeds unconditionally when EMBED_ENABLED=local (fast, no API calls).
    """
    if EMBED_ENABLED == "false":
        print("  embeddings: skipped (EMBED_ENABLED=false)")
        return

    from config import EMBED_MODEL
    import numpy as np
    from core.embedder import embed_batch
    from core.vector_index import invalidate as invalidate_index

    npy_path = CORPUS / "embeddings.npy"
    meta_path = CORPUS / "embeddings_meta.json"

    current_hash = _corpus_hash()

    # Hash-based skip — only for remote embeddings (local is fast enough to always run)
    if EMBED_ENABLED != "local" and meta_path.exists():
        try:
            stored = json.loads(meta_path.read_text(encoding="utf-8"))
            if stored.get("corpus_hash") == current_hash:
                print(
                    f"  embeddings: up to date (hash {current_hash[:12]}…) — skipping"
                )
                return
        except (ValueError, KeyError):
            pass

    print("  embeddings: building...")

    # Collect all documents in order, recording position metadata
    all_texts: list[str] = []
    all_meta: list[dict] = []

    for name in (
        "sentences_lesson.jsonl",
        "sentences_narrative.jsonl",
        "vocabulary.jsonl",
        "grammar_rules.jsonl",
        "phonemes.jsonl",
    ):
        p = CORPUS / name
        if not p.exists():
            continue
        collection = name.replace(".jsonl", "")
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if not doc.get("id"):
                continue
            # Embed text: concatenate the three most informative fields
            text = " | ".join(
                filter(
                    None,
                    [
                        doc.get("kodava", ""),
                        doc.get("english", ""),
                        doc.get("explanation", ""),
                    ],
                )
            )
            if not text.strip():
                continue
            all_texts.append(text)
            all_meta.append(
                {
                    "id": doc["id"],
                    "collection": collection,
                    "confidence": doc.get("confidence", "unverified"),
                }
            )

    if not all_texts:
        print("  embeddings: no documents to embed")
        return

    matrix = embed_batch(all_texts)  # (N, DIMS) float32
    np.save(str(npy_path), matrix)

    meta_out = {
        "corpus_hash": current_hash,
        "model": EMBED_MODEL,
        "dims": int(matrix.shape[1]),
        "count": len(all_meta),
        "docs": all_meta,
    }
    meta_path.write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    invalidate_index()
    mode = "local" if EMBED_ENABLED == "local" else EMBED_MODEL
    print(
        f"  embeddings: {len(all_meta)} docs × {matrix.shape[1]}d [{mode}] → embeddings.npy"
    )


if __name__ == "__main__":
    build()
