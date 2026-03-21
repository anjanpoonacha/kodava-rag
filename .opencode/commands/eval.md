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

## Step 1 — Reproduce retrieval

Extract the query part (before `->`) from `$ARGUMENTS` and run:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from core.retriever import search_all, invalidate
invalidate()
for r in search_all('QUERY_PART_HERE'):
    print(r.get('confidence',''), '|', r.get('english','')[:50], '|', r.get('kodava','')[:30], '|', r.get('devanagari','')[:20])
"
```

Replace `QUERY_PART_HERE` with the query part of `$ARGUMENTS`.

## Step 2 — Diagnose the layer

Follow the diagnostic workflow in the AGENTS.md "When a Test Fails" section. Identify Layer C / R / P / T.

## Step 3 — Add the promptfoo test first (TDD)

Before fixing, add a test case to `eval/promptfoo/promptfooconfig.yaml` that captures this failure.
Use `$ref` to existing `assertionTemplates` where applicable. Place in the correct suite (1–8).

Run it to confirm it currently fails:

```bash
cd eval/promptfoo && promptfoo eval --no-cache --filter-description "DESCRIPTION_OF_NEW_TEST"
```

Replace `DESCRIPTION_OF_NEW_TEST` with the `description:` value you wrote in the test case.
A failing result here proves the test correctly captures the bug.

## Step 4 — Fix the root cause

Apply the correct fix per AGENTS.md Layer guidance. If corpus was changed, rebuild:

```bash
python scripts/build_corpus.py
```

## Step 5 — Verify the test now passes

```bash
cd eval/promptfoo && promptfoo eval --no-cache --filter-description "DESCRIPTION_OF_NEW_TEST"
```

Then run the full suite to confirm no regressions:

```bash
promptfoo eval --no-cache
```

## Step 6 — Commit

If corpus was changed (commit submodule first, then pin):
```bash
cd data/thakk && git add -A && git commit -m "corpus: <describe change>" && git push
cd ../.. && git add data/thakk && git commit -m "pin thakk: <describe change>"
```

If prompt was changed:
```bash
git add prompts/ && git commit -m "prompt: <describe fix>"
```

If only eval config was changed:
```bash
git add eval/ && git commit -m "eval: add test for <describe case>"
```
