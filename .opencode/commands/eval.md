---
description: Diagnose a failing Kodava RAG query, fix root cause, add promptfoo test, verify
agent: build
subtask: true
---

@AGENTS.md

The failing prompt: $ARGUMENTS

Parse as `<query> -> <expected behavior>`:
- query = everything before `->`
- expected = everything after `->`

---

## Step 1 — Reproduce via the agent (not raw retrieval)

The `/query` endpoint routes through the SearchExpert agent, which reformulates queries
and may issue multiple targeted searches. Reproduce that exact path:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from core.agent import run_with_trace
trace = run_with_trace('QUERY_PART_HERE')
print('search calls:')
for c in trace.search_calls:
    print(' ', c.query, '|', c.collection, '|', c.hits, 'hits')
print()
print('context:')
for r in trace.all_context:
    print(' ', r.get('confidence',''), '|', r.get('english','')[:50], '|', r.get('kodava','')[:30])
print()
print('answer:', trace.answer[:300])
"
```

Replace `QUERY_PART_HERE` with the query part of `$ARGUMENTS`.

## Step 2 — Diagnose the layer

Follow the diagnostic workflow in the AGENTS.md "When a Test Fails" section.

**Layer tree — check in order:**

```
Is the word genuinely absent from corpus?
    YES → Layer C  (state gap, stop)
    NO  ↓

Does run_with_trace() produce the correct search_calls?
    NO  → Layer A  (agent query decomposition failure — fix search_agent.md)
    YES ↓

Does trace.all_context contain the relevant entry?
    NO  → Layer R  (retrieval failure — BM25/dense issue)
    YES ↓

Does the model ignore or misapply the retrieved context?
    YES → Layer P  (prompt compliance failure — fix rag_assistant.md)
    NO  ↓

Is the test query unnatural?
    YES → Layer T  (test calibration — last resort, document why)
```

**Layer A — agent decomposition failure** (new — not in AGENTS.md yet):
The retriever would find the entry with the right query, but the agent issued wrong search terms
or missed a mandatory second search (e.g., forgot `how manner` for a "how to [verb]" query).
Fix: edit `prompts/search_agent.md` — add or sharpen the relevant call-strategy rule.

## Step 3 — Add the promptfoo test first (TDD)

Before fixing, add a test case to `eval/promptfoo/promptfooconfig.yaml` that captures this failure.
Use `$ref` to existing `assertionTemplates` where applicable. Place in the correct suite (1–8).

Run it to confirm it currently fails (use `--filter-pattern`, not `--filter-description`):

```bash
cd eval/promptfoo && promptfoo eval --no-cache --filter-pattern "DESCRIPTION_OF_NEW_TEST"
```

Replace `DESCRIPTION_OF_NEW_TEST` with the `description:` value you wrote in the test case.
A failing result here proves the test correctly captures the bug.

## Step 4 — Fix the root cause

Apply the correct fix per layer:

| Layer | Fix target |
|---|---|
| C | `data/thakk/corpus/vocabulary.jsonl` — add the missing entry |
| A | `prompts/search_agent.md` — add/sharpen query decomposition rule |
| R | `data/thakk/corpus/vocabulary.jsonl` — enrich `explanation` for BM25; or `core/retriever.py` |
| P | `prompts/rag_assistant.md` — make the instruction more explicit |
| T | Change the test query to the most natural learner phrasing |

If corpus was changed, rebuild:

```bash
python scripts/build_corpus.py
```

## Step 5 — Verify the test now passes

```bash
cd eval/promptfoo && promptfoo eval --no-cache --filter-pattern "DESCRIPTION_OF_NEW_TEST"
```

Then run the full suite to confirm no regressions:

```bash
# Structural health — fast, no LLM cost (~5s)
python eval/baseline.py

# Full LLM eval suite
cd eval/promptfoo && promptfoo eval --no-cache
```

## Step 6 — Commit

**Corpus change** (commit submodule first, then pin):
```bash
cd data/thakk && git add -A && git commit -m "corpus: <describe change>" && git push
cd ../.. && git add data/thakk && git commit -m "pin thakk: <describe change>"
```

**Agent decomposition fix** (search_agent.md):
```bash
git add prompts/search_agent.md && git commit -m "agent: <describe fix>"
```

**Answer generation fix** (rag_assistant.md):
```bash
git add prompts/rag_assistant.md && git commit -m "prompt: <describe fix>"
```

**Retriever fix** (core/agent.py or core/retriever.py):
```bash
git add core/ && git commit -m "retrieval: <describe fix>"
```

**Eval config only**:
```bash
git add eval/ && git commit -m "eval: add test for <describe case>"
```
