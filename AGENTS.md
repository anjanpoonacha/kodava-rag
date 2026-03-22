# kodava-rag — Agent Setup

## Repos

| Repo | Role |
|---|---|
| `kodava-rag` | RAG application — retrieval, LLM, API, eval |
| `anjanpoonacha/thakk` | Language data — source of truth for all Kodava content |

`thakk` lives inside this workspace as a git submodule at `data/thakk/`.

---

## Branch + Worktree Setup

Three branches, each with a dedicated worktree on disk. No branch switching. No rebasing. Ever.

| Worktree | Branch | What goes here |
|---|---|---|
| `kodava-rag/` | `main` | App code, prompts, corpus config, eval suite, Dockerfile, entrypoint |
| `kodava-rag-helm/` | `feat/helm-configurable-registry` | Helm chart templates + generic defaults only — no env specifics |
| `kodava-rag-kyma/` | `deploy/kyma` | `values-kyma.yaml` only — local, **never push** |

**Initial worktree setup (one-time):**
```bash
git worktree add ../kodava-rag-helm feat/helm-configurable-registry
git worktree add ../kodava-rag-kyma deploy/kyma
```

**Staying up to date — merge, never rebase:**
```bash
# Pull app changes into helm chart branch
cd ../kodava-rag-helm && git merge main

# Pull helm chart changes into kyma branch
cd ../kodava-rag-kyma && git merge feat/helm-configurable-registry
```

**Never push `deploy/kyma`** — it contains environment-specific values.

---

## Data Flow

```
data/thakk/          ← edit language data here (submodule → anjanpoonacha/thakk)
     │
     │  python scripts/build_corpus.py
     ▼
data/corpus/         ← generated build output (gitignored, never edit directly)
     │
     │  BM25 index (rank_bm25)
     ▼
RAG pipeline (core/retriever.py + core/llm.py)
```

---

## Key Locations

### Language data — edit in `data/thakk/`

| Path | Contents |
|---|---|
| `data/thakk/corpus/vocabulary.jsonl` | Curated vocabulary entries |
| `data/thakk/corpus/sentences.jsonl` | Verified sentences and feedback |
| `data/thakk/corpus/grammar_rules.jsonl` | Grammar rules and corrections |
| `data/thakk/corpus/phonemes.jsonl` | Phoneme mappings |
| `data/thakk/phoneme_table/kodava_devanagari_map.json` | Full phoneme → Devanagari/Kannada map |
| `data/thakk/kodava_corrections.md` | Native speaker corrections |
| `data/thakk/elementary_kodava_FINAL.md` | Primary textbook source |
| `data/thakk/audio-vocab/` | Session vocab tables and transcriptions |
| `data/thakk/training_data/` | Transliteration, grammar flags, conjugations |

### Application code — edit on `main`

| Path | Contents |
|---|---|
| `prompts/rag_assistant.md` | System prompt — hot-loaded from GitHub at container startup |
| `prompts/fill_kannada.md` | Kannada script rendering rules for batch fill |
| `core/retriever.py` | BM25 search + confidence re-ranking |
| `core/llm.py` | Claude API wrapper — loads system prompt at startup |
| `core/prompts.py` | Prompt loader — fetches from GitHub, falls back to local file |
| `core/github_sync.py` | Submodule update + feedback write-back API |
| `scripts/build_corpus.py` | Corpus builder — runs all ingesters |
| `scripts/fill_kannada.py` | Batch-fill empty `kannada` fields |
| `ingesters/` | One ingester per data source type |
| `eval/baseline.py` | Structural health probe (retrieval + corpus + prompt) |
| `eval/promptfoo/` | LLM eval suite (promptfoo) |

### Helm chart — edit on `feat/helm-configurable-registry`

| Path | Contents |
|---|---|
| `charts/lingua-api/templates/` | Kubernetes manifests (Deployment, Service, APIRule, XSUAA) |
| `charts/lingua-api/values.yaml` | Default values — no environment specifics |
| `charts/lingua-api/values-override-template.yaml` | Annotated template for custom overrides |

### Kyma config — edit on `deploy/kyma`

| Path | Contents |
|---|---|
| `charts/lingua-api/values-kyma.yaml` | Environment-specific overrides (registry, host, namespace, XSUAA) |

---

## Workflows

### Update the system prompt (no image rebuild needed)

```bash
# 1. Edit on main
edit prompts/rag_assistant.md
git commit -am "prompts: <describe change>"

# 2. Restart the pod — it fetches the latest prompt from GitHub on startup
kubectl rollout restart deployment/lingua-api -n <namespace>
```

`PROMPT_FETCH=true` is set by the Helm chart. The container fetches
`prompts/rag_assistant.md` from `main` at startup, falling back to the
file baked into the image if GitHub is unreachable.

### Add or correct a word

```bash
# 1. Edit in the submodule
edit data/thakk/corpus/vocabulary.jsonl

# 2. Commit to thakk
cd data/thakk && git commit -am "corpus: add <word>" && git push

# 3. Rebuild corpus
cd ../.. && python scripts/build_corpus.py
```

### Rebuild corpus after any thakk change

```bash
python scripts/build_corpus.py
```

### Fill empty Kannada script fields

```bash
python scripts/fill_kannada.py
```

### Build and push the Docker image

```bash
# Always build for linux/amd64 — the Kyma cluster is amd64.
# Building on a Mac (arm64) without this flag produces exec format error at runtime.
# The Dockerfile pins FROM --platform=linux/amd64 — never remove that line.
docker build --platform linux/amd64 -t <registry>/<image>:<tag> .
docker push <registry>/<image>:<tag>
```

### Deploy to Kyma

```bash
# Work in the kyma worktree — no branch switching needed
cd ../kodava-rag-kyma

helm upgrade --install lingua-api ./charts/lingua-api \
  -f charts/lingua-api/values-kyma.yaml
```

### Run eval suite

```bash
cd eval/promptfoo && promptfoo eval
```

### Run a single test

Use `--filter-pattern` with a substring of the test's `description` field:

```bash
# LLM eval — match by partial description (case-insensitive)
cd eval/promptfoo && promptfoo eval --filter-pattern "house"

# Retrieval eval — same flag works
cd eval/promptfoo && promptfoo eval --config promptfooconfig.retrieval.yaml --filter-pattern "mane"
```

The flag accepts a plain string (substring match) or a `/regex/` pattern.

---

## Language Rules (Kodava Takk)

- **`oa`** is a single long-O vowel → `ಓ` in Kannada, never `ಓ+ಅ`
- **`adh`** (demonstrative "that/it") → `ಅಧ` — lexical exception to the `dh → ದ` rule
- **`d`** in Kodava = retroflex `ಡ`; **`dh`** = dental `ದ` — opposite of standard romanisation
- **Phoneme rules live in two places** — keep `prompts/fill_kannada.md` and `prompts/rag_assistant.md` in sync

---

## Data Rules

- **Never edit `data/corpus/`** — it is a generated artifact, always rebuilt by `build_corpus.py`
- **All curated language data lives in `data/thakk/`** — commit there, not here

---

## Ingesters

Each file in `data/thakk/` is handled by exactly one ingester (first match wins):

| Ingester | Matches | Output type |
|---|---|---|
| `corpus_jsonl.py` | `corpus/*.jsonl` | passthrough (preserves original IDs) |
| `vocab_table.py` | `*vocab_table*.md` | vocabulary |
| `corrections.py` | `*corrections*.md` | grammar_rule |
| `phoneme_map.py` | `*devanagari_map*.json` | phoneme |
| `elementary_kodava.py` | `elementary_kodava_FINAL.md` | vocabulary + sentence |
| `training_data.py` | `training_data/*.json[l]` | phoneme + grammar_rule |

---

## Submodule Quick Reference

```bash
# Update to latest thakk
git submodule update --remote --merge data/thakk

# After cloning kodava-rag fresh
git submodule update --init data/thakk

# Pin to a specific thakk commit
cd data/thakk && git checkout <sha>
cd ../.. && git add data/thakk && git commit -m "pin thakk to <sha>"
```

---

## Promptfoo Eval Workflow

When the user asks about anything related to promptfoo — running evals, fixing
failing tests, writing or reviewing assertions, configuring `promptfooconfig.yaml`,
debugging the Layer R/P/C/T diagnostic flow, or anything in the `eval/` directory —
you MUST delegate to the `promptfoo-expert` agent. Invoke it using the `task` tool
with `subagent_type: 'promptfoo-expert'` and a prompt that includes the full user
request plus any relevant context (failing test output, query, layer diagnosis so far).

---

## Eval — Token Rules (follow during every session)

**Do not burn tokens to locate a failure. Locate first, then evaluate.**

1. **Never use `--no-cache` during debugging.** With cache on, re-running with a
   different `--filter-pattern` costs zero LLM calls — promptfoo replays cached
   responses through new assertions. Reserve `--no-cache` for the final pre-merge
   clean run only.

2. **Run retrieval before LLM.** The retrieval suite hits no LLMs and answers
   whether the failure is Layer R in ~5 s:
   ```bash
   cd eval/promptfoo && promptfoo eval --config promptfooconfig.retrieval.yaml
   ```
   Only escalate to the LLM suite once retrieval passes.

3. **Narrow before running the full suite.** When a specific test or area is
   suspect, filter first:
   ```bash
   promptfoo eval --filter-pattern "<description substring>"
   ```
   Run the full suite only when the targeted run is green and you need to confirm
   no regressions.

4. **Order of escalation (cheapest → most expensive):**
   ```
   retrieval suite (free)
     → targeted LLM filter (cached, ~1–3 LLM calls)
       → full LLM suite (cached, ~19 LLM calls)
         → full LLM suite --no-cache (final pre-merge check only)
   ```

---

## Eval Health Check (run before every merge to main)

```bash
# 1. Structural health — retrieval, corpus, prompt (no LLM cost)
python eval/baseline.py

# 2. Retrieval correctness — BM25 layer in isolation (no LLM cost, ~5s)
cd eval/promptfoo && promptfoo eval --config promptfooconfig.retrieval.yaml --no-cache

# 3. LLM response quality — full pipeline, 19 test cases (~25s)
cd eval/promptfoo && promptfoo eval --config promptfooconfig.yaml --no-cache
```

If any test fails → diagnose root cause layer before fixing anything.

---

## When a Test Fails — Diagnostic Workflow

A failing test is a signal. Diagnose the layer first, then fix the right thing.

```
test fails
    │
    ▼
STEP 1 — Reproduce
    python3 -c "
    from core.retriever import search_all, invalidate
    invalidate()
    ctx = search_all('<query>')
    for r in ctx: print(r.get('confidence'), r.get('kodava'), r.get('english')[:30])
    "

    ▼
STEP 2 — Identify the layer

    Is the word genuinely absent from corpus?
        YES → Layer C  (expected behavior — test should assert "not in the corpus")
        NO  ↓

    Does search_all() return the relevant entry?
        NO  → Layer R  (retrieval failure)
        YES ↓

    Does the model ignore the retrieved context?
        YES → Layer P  (prompt compliance failure)
        NO  ↓

    Is the test query unnatural / no real learner would phrase it this way?
        YES → Layer T  (test calibration — last resort, document why)
        NO  → Layer P  (model behavior wrong in a way the prompt doesn't prevent)

    ▼
STEP 3 — Fix the right layer
```

### Layer R — Retrieval failure

The entry is in the corpus but the retriever doesn't find it.

**Common causes:**
- Entry `explanation` field is empty — BM25 has only 1-2 tokens to match against
- PER_COLLECTION cap (3) means the correct collection is crowded out by noise

**Fix:**
```bash
edit data/thakk/corpus/vocabulary.jsonl  # enrich explanation with natural paraphrases
cd data/thakk && git commit -am "corpus: enrich <word> explanation for BM25"
cd ../.. && python scripts/build_corpus.py
```

### Layer P — Prompt failure

Correct context is retrieved but the model ignores or misapplies an instruction.

**Fix:** Edit `prompts/rag_assistant.md` on `main`.
- Make the instruction more explicit with an inline example
- Add a negative constraint ("never omit 🟡 when confidence is textbook")
- Do NOT add new instructions without removing or replacing the conflicting old one

### Layer C — Corpus gap

Word is genuinely absent. The correct system behavior is to say so explicitly.

**Test assertion should be:**
```yaml
assert:
  - type: icontains
    value: "not in the corpus"
```

**If the word should be added:**
```bash
edit data/thakk/corpus/vocabulary.jsonl
cd data/thakk && git commit -am "corpus: add <word>"
cd ../.. && python scripts/build_corpus.py
```

### Layer T — Test calibration (last resort)

Only when: entry exists, retriever finds it, model answers correctly, but the test query is genuinely unnatural.

Fix: change the test query to the most natural phrasing a learner would actually use.
Document the root cause in the commit message.

**Rule: never change a test to make it easier to pass. Change it to be more accurate.**
