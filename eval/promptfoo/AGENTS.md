# eval/promptfoo — Agent Guide

## Directory Layout

```
eval/promptfoo/
├── promptfooconfig.yaml           # LLM suite — full RAG pipeline quality
├── promptfooconfig.retrieval.yaml # Retrieval suite — BM25 layer, no LLM calls
├── promptfooconfig.agent.yaml     # Agent suite — SearchingExpert tool-use loop
│
├── configs/
│   ├── grader.yaml                # Shared grader (Haiku via proxy) — never edit per-run
│   └── rag-provider.yaml          # Shared RAG provider definition
│
├── tests/
│   ├── llm/
│   │   ├── corpus_guard.yaml      # "not in corpus" refusal tests
│   │   ├── format.yaml            # bold / table / script format checks
│   │   ├── vocabulary.yaml        # core vocab + grammar correctness
│   │   ├── script.yaml            # Kannada / Devanagari rendering
│   │   ├── confidence.yaml        # ⚠️ flag on derived/unverified forms
│   │   ├── composition.yaml       # paragraph, connectives, context-faithfulness
│   │   └── tdd.yaml               # ← NEW REGRESSIONS LAND HERE
│   ├── retrieval/
│   │   ├── hits.yaml              # exact vocabulary / grammar lookups
│   │   ├── kannada_script.yaml    # Kannada-script BM25 index checks
│   │   └── cross_collection.yaml  # search_all fanout + id-pin regressions
│   └── agent/
│       ├── reformulation.yaml     # query reformulation (suites A + H)
│       ├── collection_targeting.yaml  # collection routing (suite B)
│       ├── retry_and_limits.yaml  # retry + 2-call cap (suites C + I)
│       ├── corpus_guard.yaml      # fabrication guard + keyword guard (suites D + G)
│       └── faithfulness.yaml      # answer faithfulness + script (suites E + F)
│
├── provider.py                    # call_api | retrieve | call_agent
├── grader.py                      # custom grader utilities (if any)
└── .env                           # ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL_GRADER
```

---

## Running Evals

```bash
# All commands from eval/promptfoo/
cd eval/promptfoo

# Full LLM suite (~25s with cache)
promptfoo eval

# Retrieval only — zero API cost (~5s)
promptfoo eval --config promptfooconfig.retrieval.yaml

# Agent suite
promptfoo eval --config promptfooconfig.agent.yaml

# Single test by description substring
promptfoo eval --filter-pattern "house"
promptfoo eval --config promptfooconfig.agent.yaml --filter-pattern "morning"

# Force fresh API calls (no cache)
promptfoo eval --no-cache

# CI mode
PROMPTFOO_CACHE_ENABLED=false promptfoo eval

# Open web UI after a run
promptfoo view
```

### Speed tiers

| Tier | What | Time |
|------|------|------|
| Fast | retrieval suite (zero LLM) | ~5s |
| Fast | LLM suite, icontains/regex only (`corpus_guard`, `format`, `script`) | ~5s |
| Slow | LLM suite including `llm-rubric` assertions | ~25s |
| Slow | Agent suite | ~40s |

To run only the fast LLM tests:

```bash
promptfoo eval --filter-pattern "vocab|format|script"
```

---

## Adding a New Test (TDD Workflow)

**Rule: new regressions go to `tests/llm/tdd.yaml` first.**

1. A test is failing or a new behaviour needs covering → add it to `tdd.yaml`
2. Run just the new test while iterating:
   ```bash
   promptfoo eval --filter-pattern "<your description substring>"
   ```
3. Diagnose the failing layer (see AGENTS.md at repo root for the diagnostic workflow)
4. Fix corpus / retrieval / prompt as needed
5. Once the test is green, move it to the correct stable file:

| What the test covers | Target file |
|---|---|
| `not in the corpus` refusal | `corpus_guard.yaml` |
| Bold / table / length / script format | `format.yaml` |
| Core vocabulary or grammar correctness | `vocabulary.yaml` |
| Kannada or Devanagari rendering | `script.yaml` |
| ⚠️ flag on derived forms | `confidence.yaml` |
| Paragraphs, connectives, RAG faithfulness | `composition.yaml` |

6. Commit corpus + test together with a clear message:
   ```
   corpus: add <word> — fixes tdd regression for <description>
   ```

**Never accumulate stale tests in `tdd.yaml`.** It should be empty (or near-empty) on `main`.

---

## Shared Config Files (`configs/`)

These are referenced via `file://` from every top-level config. Edit them centrally:

| File | What it controls |
|---|---|
| `configs/grader.yaml` | Grader model, API key, base URL |
| `configs/rag-provider.yaml` | RAG pipeline provider entrypoint |

If the grader model or proxy URL changes, update `configs/grader.yaml` once — all three suites pick it up.

---

## Providers (`provider.py`)

| Function | Used by | What it does |
|---|---|---|
| `call_api` | `promptfooconfig.yaml` | Full RAG: retrieval + Claude answer generation |
| `retrieve` | `promptfooconfig.retrieval.yaml` | BM25 retrieval only — returns raw JSON, no LLM |
| `call_agent` | `promptfooconfig.agent.yaml` | SearchingExpert agent: tool-use loop + answer |

All functions return `metadata.search_calls` and `metadata.context` so promptfoo
assertions can inspect retrieval behaviour (query reformulation, collection targeting, etc.).

---

## Diagnostic Workflow (test failure)

See the full diagnostic flowchart in `AGENTS.md` at the repo root.
Short version:

```
test fails
  → check search_all() — is the word in context?
      NO  → Layer R: retrieval failure (enrich corpus explanation field)
      YES → check if model ignores context
              YES → Layer P: prompt failure (edit prompts/rag_assistant.md)
              NO  → Layer C: corpus gap (add word to data/thakk/corpus/)
                   or Layer T: test calibration (last resort — change query)
```

After any corpus change: `python scripts/build_corpus.py`

---

## What Lives Where (rule of thumb)

| Change | Where to make it |
|---|---|
| New word or sentence | `data/thakk/corpus/` (submodule) |
| Phoneme rule | `data/thakk/phoneme_table/` |
| Prompt instruction | `prompts/rag_assistant.md` |
| New eval regression | `tests/llm/tdd.yaml` → stable suite |
| Grader model/URL | `configs/grader.yaml` |
| New retrieval behaviour | `tests/retrieval/` |
| New agent behaviour | `tests/agent/` |
