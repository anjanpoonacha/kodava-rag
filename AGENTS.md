# kodava-rag — Agent Setup

## Repos

| Repo | Role |
|---|---|
| `kodava-rag` | RAG application — retrieval, LLM, API, eval |
| `anjanpoonacha/thakk` | Language data — source of truth for all Kodava content |

`thakk` lives inside this workspace as a git submodule at `data/thakk/`.

---

## Data Flow

```
data/thakk/          ← edit language data here (submodule)
     │
     │  make corpus  (git submodule update --remote, then ingesters)
     ▼
data/corpus/         ← generated build output (gitignored)
     │
     │  BM25 index
     ▼
RAG pipeline (core/retriever.py + core/llm.py)
```

---

## Key Locations

### Language data — edit in `data/thakk/`

| Path | Contents |
|---|---|
| `data/thakk/corpus/vocabulary.jsonl` | Curated vocabulary + seed entries |
| `data/thakk/corpus/sentences.jsonl` | Verified sentences and feedback |
| `data/thakk/corpus/grammar_rules.jsonl` | Grammar rules and corrections |
| `data/thakk/corpus/phonemes.jsonl` | Phoneme mappings |
| `data/thakk/phoneme_table/kodava_devanagari_map.json` | Full phoneme → Devanagari/Kannada map |
| `data/thakk/kodava_corrections.md` | Native speaker corrections |
| `data/thakk/elementary_kodava_FINAL.md` | Primary textbook source |
| `data/thakk/audio-vocab/` | Session vocab tables and transcriptions |
| `data/thakk/training_data/` | Transliteration, grammar flags, conjugations |

### Application — edit in `kodava-rag/`

| Path | Contents |
|---|---|
| `prompts/rag_assistant.md` | Main system prompt — phoneme rules, confidence flags, formatting |
| `prompts/fill_kannada.md` | Kannada script rendering rules — critical phoneme exceptions |
| `ingesters/` | One ingester per data source type |
| `core/retriever.py` | BM25 search + confidence re-ranking |
| `core/llm.py` | Claude API wrapper |
| `core/github_sync.py` | Submodule update + feedback write-back API |
| `scripts/fill_kannada.py` | Batch-fill empty `kannada` fields in corpus |
| `eval/promptfoo/` | LLM eval suite (promptfoo) |

---

## Workflows

### Add or correct a word
```bash
# 1. Edit directly in the submodule
edit data/thakk/corpus/vocabulary.jsonl

# 2. Commit to thakk
cd data/thakk && git commit -am "corpus: add <word>" && git push

# 3. Rebuild
cd ../.. && make corpus
```

### Rebuild corpus after any thakk change
```bash
make corpus   # pulls latest submodule commit + runs all ingesters
```

### Fill empty Kannada script fields
```bash
python scripts/fill_kannada.py
```

### Run eval suite
```bash
cd eval/promptfoo && npx promptfoo eval
```

---

## Rules

- **Never edit `data/corpus/`** — it is a generated artifact, gitignored, always rebuilt by `make corpus`
- **All curated language data lives in `data/thakk/`** — commit there, not here
- **Phoneme rules live in two places** — `prompts/fill_kannada.md` (for batch fill) and `prompts/rag_assistant.md` (for live RAG responses). Keep them in sync
- **`oa` is a single long-O vowel** → `ಓ` in Kannada, never `ಓ+ಅ`
- **`adh` (demonstrative "that/it") → `ಅಧ`** — lexical exception to the `dh → ದ` phoneme rule
- **`d` in Kodava = retroflex `ಡ`**, `dh` = dental `ದ` — opposite of standard romanization

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

## Eval Health Check (run before every merge to main)

```bash
# 1. Structural health — retrieval, corpus, prompt checks (no LLM cost)
python eval/baseline.py

# 2. Retrieval correctness — BM25 layer in isolation (no LLM cost, ~5s)
cd eval/promptfoo && promptfoo eval --config promptfooconfig.retrieval.yaml --no-cache

# 3. LLM response quality — full pipeline, 19 test cases (~25s)
cd eval/promptfoo && promptfoo eval --config promptfooconfig.yaml
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
- Query has trailing punctuation (`morning?` ≠ `morning` in BM25) — fixed in retriever
- Entry `explanation` field is empty so BM25 has only 2-3 tokens to match against
- PER_COLLECTION cap (3) means correct collection is crowded out by noise

**Fix:**
```bash
# Enrich the corpus entry explanation field in data/thakk
edit data/thakk/corpus/vocabulary.jsonl  # add explanation with natural paraphrases
cd data/thakk && git commit -am "corpus: enrich <word> explanation for BM25"
cd ../.. && make corpus
```

### Layer P — Prompt failure

Correct context is retrieved but the model ignores or misapplies an instruction.

**Fix:** Edit `prompts/rag_assistant.md`.
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
cd ../.. && make corpus
```

### Layer T — Test calibration (last resort)

Only when: entry exists, retriever finds it, model answers correctly, but the test query is genuinely unnatural.

Fix: change the test query to the most natural phrasing a learner would actually use.
Document the root cause in the commit message.

**Rule: never change a test to make it easier to pass. Change it to be more accurate.**
