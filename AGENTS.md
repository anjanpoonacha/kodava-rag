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
