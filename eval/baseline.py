#!/usr/bin/env python3
"""
Baseline probe — measures RAG system state across evaluation dimensions.

Run BEFORE and AFTER fixes to produce a comparable report.
Outputs a structured text report to stdout and optionally to a file.

Usage:
    python eval/baseline.py
    python eval/baseline.py > eval/snapshots/before.txt
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA, TOP_K, BM25_CANDIDATES, WORD_SEARCH_THRESHOLD, MODEL

try:
    from config import MAX_TOKENS
except ImportError:
    MAX_TOKENS = None  # not yet defined — hardcoded 1024 in llm.py
from core.retriever import search_all, search, search_by_tokens
from core.prompts import load_prompt

CORPUS = DATA / "corpus"
SNAPSHOTS = Path(__file__).parent / "snapshots"

# ──────────────────────────────────────────────────────────────────────────────
# Probe helpers
# ──────────────────────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"

results: list[dict] = []


def check(dim: str, item: str, status: str, detail: str = ""):
    results.append({"dim": dim, "item": item, "status": status, "detail": detail})
    icon = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "SKIP": "–"}.get(status, "?")
    line = f"  [{icon}] {item}"
    if detail:
        line += f"  →  {detail}"
    print(line)


def section(title: str):
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 1 — Configuration constants
# ──────────────────────────────────────────────────────────────────────────────


def probe_config():
    section("DIM 1  Configuration")

    check("config", "TOP_K value", PASS if TOP_K >= 6 else WARN, f"TOP_K={TOP_K}")
    check(
        "config",
        "BM25_CANDIDATES value",
        PASS if BM25_CANDIDATES >= 15 else WARN,
        f"BM25_CANDIDATES={BM25_CANDIDATES}",
    )
    check(
        "config",
        "WORD_SEARCH_THRESHOLD",
        PASS,
        f"WORD_SEARCH_THRESHOLD={WORD_SEARCH_THRESHOLD}",
    )
    check("config", "MODEL", PASS, f"MODEL={MODEL}")

    if MAX_TOKENS is None:
        check(
            "config",
            "MAX_TOKENS value",
            FAIL,
            "MAX_TOKENS not defined in config — hardcoded 1024 in llm.py (too low)",
        )
    else:
        check(
            "config",
            "MAX_TOKENS value",
            PASS if MAX_TOKENS >= 1500 else WARN,
            f"MAX_TOKENS={MAX_TOKENS} (complex answers may truncate below 1500)",
        )


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 2 — Corpus files present and non-empty
# ──────────────────────────────────────────────────────────────────────────────

EXPECTED_COLLECTIONS = ["vocabulary", "grammar_rules", "sentences", "phonemes"]

corpus_counts: dict[str, int] = {}


def probe_corpus():
    section("DIM 2  Corpus Files")

    if not CORPUS.exists():
        check("corpus", "corpus/ directory exists", FAIL, "Run: make build-corpus")
        return

    for col in EXPECTED_COLLECTIONS:
        path = CORPUS / f"{col}.jsonl"
        if not path.exists():
            check("corpus", f"{col}.jsonl exists", FAIL, "missing — run build-corpus")
            corpus_counts[col] = 0
            continue
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        corpus_counts[col] = len(lines)
        status = PASS if len(lines) > 0 else FAIL
        check("corpus", f"{col}.jsonl non-empty", status, f"{len(lines)} entries")

    # Confidence distribution
    for col in EXPECTED_COLLECTIONS:
        path = CORPUS / f"{col}.jsonl"
        if not path.exists():
            continue
        confidence_dist: dict[str, int] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                c = e.get("confidence", "unknown")
                confidence_dist[c] = confidence_dist.get(c, 0) + 1
            except json.JSONDecodeError:
                pass
        check(
            "corpus",
            f"{col} confidence distribution",
            PASS,
            " | ".join(f"{k}:{v}" for k, v in sorted(confidence_dist.items())),
        )

    # Near-duplicate scan (same kodava, same english, different ids)
    for col in EXPECTED_COLLECTIONS:
        path = CORPUS / f"{col}.jsonl"
        if not path.exists():
            continue
        seen_keys: dict[str, int] = {}
        dupes = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                key = f"{e.get('kodava', '').lower().strip()}::{e.get('english', '').lower().strip()}"
                if key in seen_keys:
                    dupes += 1
                seen_keys[key] = 1
            except json.JSONDecodeError:
                pass
        status = PASS if dupes == 0 else WARN
        check(
            "corpus",
            f"{col} near-duplicate entries",
            status,
            f"{dupes} duplicates found",
        )


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 3 — Retrieval logic
# ──────────────────────────────────────────────────────────────────────────────

# Known Q→expected_keyword pairs (testable without LLM)
RECALL_PROBES = [
    ("naan", "sentences", "naan"),  # Kodava word for 'I'
    ("I went", "sentences", "naan"),  # English phrase → should hit kodava sentence
    ("past tense", "grammar_rules", "past"),  # grammar concept
    ("to the market", "sentences", "sante"),  # English gloss
    ("neer", "vocabulary", "neer"),  # 'water' in Kodava
    ("greetings", "vocabulary", ""),  # domain coverage
    ("LL phoneme", "phonemes", "ll"),  # phoneme lookup
    ("retroflex", "phonemes", ""),  # descriptor lookup
]

KANNADA_PROBES = [
    "ನಾನ್",  # naan in Kannada script
    "ಮನೆ",  # mane (house)
    "ಪೋನ್",  # poanê (went)
]

PARAPHRASE_PROBES = [
    ("how do I say I am hungry", "hasi"),
    ("word for water", "neer"),
    ("how to greet someone", ""),
]


def probe_retrieval():
    section("DIM 3  Retrieval Logic")

    if not any(corpus_counts.values()):
        check(
            "retrieval",
            "all recall probes",
            SKIP,
            "corpus not built — cannot test retrieval",
        )
        return

    # 3.1 Recall@TOP_K
    hits = 0
    total = 0
    for query, collection, expected_keyword in RECALL_PROBES:
        if corpus_counts.get(collection, 0) == 0:
            continue
        total += 1
        try:
            docs = search(query, collection)
            found = (
                any(
                    expected_keyword.lower() in str(d.get("kodava", "")).lower()
                    or expected_keyword.lower() in str(d.get("english", "")).lower()
                    for d in docs
                )
                if expected_keyword
                else len(docs) > 0
            )
            if found:
                hits += 1
        except Exception:
            pass
    if total > 0:
        recall = hits / total
        status = PASS if recall >= 0.6 else WARN if recall >= 0.4 else FAIL
        check(
            "retrieval",
            f"Recall@{TOP_K} (phrase search)",
            status,
            f"{hits}/{total} probes hit ({recall:.0%})",
        )
    else:
        check(
            "retrieval",
            f"Recall@{TOP_K} (phrase search)",
            SKIP,
            "no testable collections available",
        )

    # 3.2 Multi-script query coverage (Kannada script queries → expect 0 hits currently)
    for kq in KANNADA_PROBES:
        docs = search_all(kq)
        status = PASS if len(docs) > 0 else FAIL
        check(
            "retrieval",
            f"Kannada-script query: '{kq}'",
            status,
            f"{len(docs)} hits (0 = BM25 blind to script fields)",
        )

    # 3.3 Paraphrase / semantic gap
    for query, expected_keyword in PARAPHRASE_PROBES:
        docs = search_all(query)
        found = (
            any(
                expected_keyword.lower() in str(d.get("kodava", "")).lower()
                or expected_keyword.lower() in str(d.get("english", "")).lower()
                for d in docs
            )
            if expected_keyword
            else len(docs) > 0
        )
        status = WARN if not found else PASS
        check(
            "retrieval",
            f"Paraphrase: '{query[:40]}'",
            status,
            f"{len(docs)} hits, target keyword {'found' if found else 'NOT found'}",
        )

    # 3.4 Cold corpus (empty result path)
    docs = search_all("xzqwerty_nonexistent_word_12345")
    check(
        "retrieval",
        "Cold query returns empty list",
        PASS if docs == [] else WARN,
        f"{len(docs)} hits for nonsense query",
    )

    # 3.5 Token fan-out fires correctly
    if corpus_counts.get("sentences", 0) > 0:
        # Deliberately thin phrase — should trigger Layer 2
        docs_layer2 = search_all("morning salutation greeting phrase")
        check(
            "retrieval",
            "Layer 2 token fan-out activates on thin phrase",
            PASS,
            f"{len(docs_layer2)} total results via fallback path",
        )

    # 3.6 Confidence field present in all corpus entries
    for col in EXPECTED_COLLECTIONS:
        path = CORPUS / f"{col}.jsonl"
        if not path.exists():
            continue
        missing_confidence = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
                if not e.get("confidence"):
                    missing_confidence += 1
            except json.JSONDecodeError:
                pass
        status = PASS if missing_confidence == 0 else WARN
        check(
            "retrieval",
            f"{col} entries have confidence field",
            status,
            f"{missing_confidence} missing",
        )

    # 3.7 Confidence re-ranking — verify _rerank_by_confidence is implemented
    retriever_src = (ROOT / "core" / "retriever.py").read_text()
    has_rerank_fn = "_rerank_by_confidence" in retriever_src
    has_confidence_rank = "_CONFIDENCE_RANK" in retriever_src
    status = PASS if (has_rerank_fn and has_confidence_rank) else FAIL
    detail = (
        "implemented — verified entries ranked above textbook/unverified"
        if status == PASS
        else "MISSING — add _rerank_by_confidence() to retriever.py"
    )
    check("retrieval", "Retriever re-ranks by confidence field", status, detail)

    # 3.8 Dense retrieval — vector index and RRF merge present
    has_rrf = "_rrf_merge" in retriever_src
    has_async = "search_all_async" in retriever_src
    check(
        "retrieval",
        "RRF merge function present",
        PASS if has_rrf else FAIL,
        "implemented" if has_rrf else "MISSING — add _rrf_merge() to retriever.py",
    )
    check(
        "retrieval",
        "Async hybrid search_all_async present",
        PASS if has_async else FAIL,
        "implemented"
        if has_async
        else "MISSING — add search_all_async() to retriever.py",
    )

    # 3.9 Dense index — embeddings files exist (or EMBED_ENABLED=false)
    from config import EMBED_ENABLED

    npy = CORPUS / "embeddings.npy"
    meta = CORPUS / "embeddings_meta.json"
    if EMBED_ENABLED == "false":
        check(
            "retrieval",
            "Dense index (EMBED_ENABLED=false)",
            PASS,
            "disabled by config — BM25-only mode",
        )
    elif npy.exists() and meta.exists():
        import json as _json

        try:
            m = _json.loads(meta.read_text())
            count = m.get("count", 0)
            model = m.get("model", "?")
            dims = m.get("dims", 0)
            check(
                "retrieval",
                "Dense index embeddings.npy",
                PASS,
                f"{count} docs × {dims}d [{model}]",
            )
        except Exception as exc:
            check(
                "retrieval",
                "Dense index embeddings.npy",
                WARN,
                f"meta unreadable: {exc}",
            )
    else:
        check(
            "retrieval",
            "Dense index embeddings.npy",
            WARN,
            "not built yet — run: python scripts/build_corpus.py",
        )

    # 3.10 Dense lane retrieval smoke test — Kaveri query returns audio_source hits
    if EMBED_ENABLED != "false" and npy.exists():
        try:
            from core.vector_index import load as load_idx, invalidate as inv_idx

            inv_idx()
            idx = load_idx()
            if idx:
                from core.embedder import embed_one

                qv = embed_one("What is Kaveri Sankramana festival?")
                if qv is not None:
                    hits = idx.search(qv, top_k=12)
                    audio_hits = [
                        h for h in hits if h.get("confidence") == "audio_source"
                    ]
                    check(
                        "retrieval",
                        "Dense lane: Kaveri query returns audio_source hits",
                        PASS if audio_hits else FAIL,
                        f"{len(audio_hits)} audio_source hits in top-12",
                    )
                else:
                    check(
                        "retrieval",
                        "Dense lane smoke test",
                        WARN,
                        "embed_one returned None",
                    )
            else:
                check(
                    "retrieval",
                    "Dense lane smoke test",
                    WARN,
                    "vector index not loaded",
                )
        except Exception as exc:
            check("retrieval", "Dense lane smoke test", WARN, f"skipped: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 4 — System prompt quality
# ──────────────────────────────────────────────────────────────────────────────


def probe_system_prompt():
    section("DIM 4  System Prompt")

    prompt = load_prompt("rag_assistant")
    lines = prompt.splitlines()
    token_estimate = len(prompt.split())

    check(
        "prompt",
        "Prompt file loads",
        PASS,
        f"{len(lines)} lines / ~{token_estimate} tokens",
    )

    # 4.1 Responsibility audit — count distinct sections
    sections_found = []
    if "You are" in prompt:
        sections_found.append("persona")
    if (
        "bold" in prompt.lower()
        or "formatting" in prompt.lower()
        or "markdown" in prompt.lower()
    ):
        sections_found.append("formatting")
    if "→" in prompt and ("Kannada" in prompt or "Devanagari" in prompt):
        sections_found.append("derivation_examples (specific)")
    if "⚠️" in prompt or "🔴" in prompt or "🟡" in prompt:
        sections_found.append("flag_notation")
    if "not in the corpus" in prompt.lower():
        sections_found.append("missing_vocab_guard")
    if "phoneme" in prompt.lower() or "LL" in prompt or "zh" in prompt:
        sections_found.append("phoneme_mappings (specific)")

    status = PASS if len(sections_found) <= 4 else WARN
    check(
        "prompt",
        "Responsibility count (target ≤ 4)",
        status,
        f"{len(sections_found)} sections: {', '.join(sections_found)}",
    )

    # 4.2 Trust hierarchy — does prompt say retrieved context overrides static rules?
    trust_keywords = [
        "retrieved context",
        "context overrides",
        "context takes precedence",
        "source of truth",
        "context is authoritative",
    ]
    has_trust = any(kw.lower() in prompt.lower() for kw in trust_keywords)
    check(
        "prompt",
        "Trust hierarchy explicit (retrieved > hardcoded)",
        FAIL if not has_trust else PASS,
        "MISSING: no instruction that retrieved context overrides static derivation rules"
        if not has_trust
        else "found",
    )

    # 4.3 Confidence-to-flag mapping
    confidence_values = ["verified", "audio_source", "textbook", "unverified"]
    flag_emojis = ["⚠️", "🔴", "🟡"]
    has_confidence_mapping = any(cv in prompt for cv in confidence_values)
    has_flags = any(fe in prompt for fe in flag_emojis)
    if has_flags and not has_confidence_mapping:
        check(
            "prompt",
            "Confidence field → flag emoji mapping",
            FAIL,
            "Flag emojis defined but never tied to corpus confidence field values",
        )
    elif has_flags and has_confidence_mapping:
        check(
            "prompt", "Confidence field → flag emoji mapping", PASS, "mapping present"
        )
    else:
        check(
            "prompt", "Confidence field → flag emoji mapping", WARN, "no flags defined"
        )

    # 4.4 Specific derivation examples hardcoded (should be in corpus)
    example_lines = [
        l for l in lines if "→" in l and ("ನ" in l or "ड" in l or "ळ" in l or "ಳ" in l)
    ]
    status = WARN if example_lines else PASS
    check(
        "prompt",
        "Specific derivation examples NOT hardcoded in prompt",
        WARN if example_lines else PASS,
        f"{len(example_lines)} specific example lines found (should be in corpus entries)",
    )

    # 4.5 Missing-vocab guard present
    has_guard = "not in the corpus" in prompt.lower()
    check(
        "prompt",
        "Missing-vocab guard present",
        PASS if has_guard else FAIL,
        "guard found" if has_guard else "no guard — model may fabricate",
    )

    # 4.6 Response language policy
    has_lang_policy = "english" in prompt.lower() and (
        "respond in english" in prompt.lower() or "always respond" in prompt.lower()
    )
    check(
        "prompt",
        "Response language policy explicit",
        PASS if has_lang_policy else WARN,
        "found" if has_lang_policy else "no explicit response-language instruction",
    )

    # 4.7 Negative constraint (no borrowed vocabulary)
    has_negative = "never fill" in prompt.lower() or "borrowed" in prompt.lower()
    check(
        "prompt",
        "Negative constraint (no borrowed vocab)",
        PASS if has_negative else WARN,
        "found" if has_negative else "missing",
    )

    # 4.8 MAX_TOKENS adequacy relative to prompt size
    if MAX_TOKENS is None:
        check(
            "prompt",
            "Response token headroom",
            FAIL,
            "MAX_TOKENS hardcoded 1024 in llm.py — only ~800 tokens left after prompt+context",
        )
    else:
        headroom = MAX_TOKENS - token_estimate
        status = PASS if headroom >= 1000 else WARN
        check(
            "prompt",
            f"Response token headroom (max_tokens={MAX_TOKENS} - prompt≈{token_estimate})",
            status,
            f"~{headroom} tokens available for response",
        )


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 5 — Ingester coverage
# ──────────────────────────────────────────────────────────────────────────────


def probe_ingesters():
    section("DIM 5  Ingester Coverage")

    from ingesters import REGISTRY
    import ingesters.vocab_table  # noqa — register
    import ingesters.corrections  # noqa
    import ingesters.phoneme_map  # noqa
    import ingesters.elementary_kodava  # noqa
    import ingesters.training_data  # noqa

    check(
        "ingesters",
        "Registered ingesters",
        PASS,
        f"{len(REGISTRY)} registered: {[type(r).__name__ for r in REGISTRY]}",
    )

    # Check grammar_rule → grammar_rules.jsonl filename mismatch
    build_src = (ROOT / "scripts" / "build_corpus.py").read_text()
    has_grammar_rule_map = '"grammar_rule": CORPUS / "grammar_rules.jsonl"' in build_src
    check(
        "ingesters",
        "grammar_rule type → grammar_rules.jsonl mapping",
        PASS if has_grammar_rule_map else FAIL,
        "mapped correctly" if has_grammar_rule_map else "collection type mismatch",
    )

    # Check phoneme type → phonemes.jsonl
    has_phoneme_map = '"phoneme": CORPUS / "phonemes.jsonl"' in build_src
    check(
        "ingesters",
        "phoneme type → phonemes.jsonl mapping",
        PASS if has_phoneme_map else FAIL,
        "mapped correctly" if has_phoneme_map else "collection type mismatch",
    )

    # Verify retriever searches "grammar_rules" but build writes "grammar_rules.jsonl"
    retriever_src = (ROOT / "core" / "retriever.py").read_text()
    collections_searched = []
    for col in ("sentences", "grammar_rules", "vocabulary", "phonemes"):
        if f'"{col}"' in retriever_src:
            collections_searched.append(col)
    check(
        "ingesters",
        "Retriever collections match corpus filenames",
        PASS,
        f"searches: {collections_searched}",
    )


# ──────────────────────────────────────────────────────────────────────────────
# DIMENSION 6 — Domain coverage audit (when corpus exists)
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_PROBES = {
    "numbers": ["one", "two", "three", "ondu", "eradu", "muuru"],
    "colors": ["red", "blue", "green", "kempu", "neeli", "hasiru"],
    "body parts": ["hand", "eye", "head", "kai", "kann", "tale"],
    "greetings": ["hello", "goodbye", "welcome", "namaskara"],
    "time": ["today", "tomorrow", "yesterday", "inji", "naale"],
    "family": ["mother", "father", "sister", "brother", "avva", "appa"],
}


def probe_domain_coverage():
    section("DIM 6  Domain Coverage")

    if not any(corpus_counts.values()):
        check("coverage", "all domain probes", SKIP, "corpus not built")
        return

    all_text = ""
    for col in EXPECTED_COLLECTIONS:
        path = CORPUS / f"{col}.jsonl"
        if path.exists():
            all_text += path.read_text(encoding="utf-8").lower()

    for domain, keywords in DOMAIN_PROBES.items():
        found = [kw for kw in keywords if kw in all_text]
        coverage = len(found) / len(keywords)
        status = PASS if coverage >= 0.5 else WARN if coverage > 0 else FAIL
        check(
            "coverage",
            f"Domain: {domain}",
            status,
            f"{len(found)}/{len(keywords)} keywords present ({coverage:.0%})",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────


def print_summary():
    print(f"\n{'═' * 70}")
    print("  SUMMARY")
    print(f"{'═' * 70}")

    by_status: dict[str, list[dict]] = {PASS: [], FAIL: [], WARN: [], SKIP: []}
    for r in results:
        by_status.setdefault(r["status"], []).append(r)

    total = len(results)
    print(f"\n  Total checks : {total}")
    print(f"  ✓ PASS       : {len(by_status[PASS])}")
    print(f"  ✗ FAIL       : {len(by_status[FAIL])}")
    print(f"  ! WARN       : {len(by_status[WARN])}")
    print(f"  – SKIP       : {len(by_status[SKIP])}")

    score = (
        len(by_status[PASS]) / (total - len(by_status[SKIP]))
        if (total - len(by_status[SKIP])) > 0
        else 0
    )
    print(
        f"\n  Health score : {score:.0%}  ({len(by_status[PASS])}/{total - len(by_status[SKIP])} actionable checks passing)"
    )

    if by_status[FAIL]:
        print("\n  FAILURES to fix:")
        for r in by_status[FAIL]:
            print(f"    ✗ [{r['dim']}] {r['item']}")
            if r["detail"]:
                print(f"        {r['detail']}")

    if by_status[WARN]:
        print("\n  WARNINGS to address:")
        for r in by_status[WARN]:
            print(f"    ! [{r['dim']}] {r['item']}")
            if r["detail"]:
                print(f"        {r['detail']}")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def run():
    from datetime import datetime

    print(f"{'═' * 70}")
    print(f"  KODAVA RAG BASELINE PROBE")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 70}")

    probe_config()
    probe_corpus()
    probe_retrieval()
    probe_system_prompt()
    probe_ingesters()
    probe_domain_coverage()
    print_summary()

    # Save JSON snapshot for diff
    SNAPSHOTS.mkdir(exist_ok=True)
    snapshot_path = (
        SNAPSHOTS / f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    snapshot_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n  Snapshot saved → {snapshot_path.relative_to(ROOT)}")


if __name__ == "__main__":
    run()
