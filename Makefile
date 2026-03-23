.PHONY: help install corpus phonemes fill-kannada check-vocab query api \
        eval eval-retrieval eval-llm baseline \
        transcribe transcribe-vocab sync push-thakk \
        thakk-update thakk-push

# Default target — print help
help:
	@echo ""
	@echo "kodava-rag — common workflows"
	@echo ""
	@echo "  Setup"
	@echo "    make install           Install Python dependencies"
	@echo ""
	@echo "  Corpus (run after editing data/thakk/)"
	@echo "    make corpus            Rebuild data/corpus/ from all thakk sources"
	@echo "    make fill-kannada      Batch-fill empty Kannada script fields"
	@echo "    make phonemes          Regenerate phoneme rule tables in all prompts"
	@echo "    make check-vocab       Scan vocab tables for word-final e rendering errors"
	@echo ""
	@echo "  Queries"
	@echo "    make query Q=\"...\"     Run a single query against the RAG pipeline"
	@echo "    make api               Start the API server on http://localhost:8000"
	@echo ""
	@echo "  Eval"
	@echo "    make baseline          Structural health probe (no LLM cost)"
	@echo "    make eval-retrieval    BM25 retrieval correctness (no LLM cost)"
	@echo "    make eval-llm          Full LLM eval suite (uses Claude)"
	@echo "    make eval              baseline + eval-retrieval + eval-llm"
	@echo ""
	@echo "  Transcription"
	@echo "    make transcribe FILE=path/to/audio.mp3   Transcribe audio → transcript"
	@echo "    make transcribe-vocab FILE=path/to/transcription.md  Extract vocab table"
	@echo ""
	@echo "  thakk submodule"
	@echo "    make thakk-update      Pull latest thakk (git submodule update --remote)"
	@echo "    make thakk-push        Commit and push changes in data/thakk/"
	@echo "    make push-thakk MSG=\"msg\"  Same as thakk-push with a custom message"
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

install:
	pip install -r requirements.txt
	pip install -e .

# ─────────────────────────────────────────────────────────────────────────────
# Corpus
# ─────────────────────────────────────────────────────────────────────────────

corpus:
	python scripts/build_corpus.py

fill-kannada:
	python scripts/fill_kannada.py

# Regenerate phoneme rule tables in fill_kannada.md, rag_assistant.md,
# and transcribe_audio.py from the single source of truth:
#   data/thakk/phoneme_table/kodava_devanagari_map.json
phonemes:
	python scripts/generate_phoneme_rules.py
	@echo ""
	@echo "Review: git diff prompts/ scripts/transcribe_audio.py"
	@echo "Commit: git add prompts/ scripts/transcribe_audio.py && git commit -m 'prompts: regenerate phoneme rules'"

# Scan all audio-vocab session vocab tables for word-final 'e' rendering errors
check-vocab:
	python scripts/check_vocab_tables.py

# ─────────────────────────────────────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────────────────────────────────────

query:
	@test -n "$(Q)" || (echo "Usage: make query Q=\"how do I say house\"" && exit 1)
	python query.py "$(Q)"

api:
	python3 -m uvicorn api.app:app --reload

# ─────────────────────────────────────────────────────────────────────────────
# Eval
# ─────────────────────────────────────────────────────────────────────────────

baseline:
	python eval/baseline.py

eval-retrieval:
	cd eval/promptfoo && promptfoo eval --config promptfooconfig.retrieval.yaml

eval-llm:
	cd eval/promptfoo && promptfoo eval --config promptfooconfig.yaml

eval: baseline eval-retrieval eval-llm

# ─────────────────────────────────────────────────────────────────────────────
# Transcription
# ─────────────────────────────────────────────────────────────────────────────

transcribe:
	@test -n "$(FILE)" || (echo "Usage: make transcribe FILE=path/to/audio.mp3" && exit 1)
	python scripts/transcribe_audio.py "$(FILE)"

transcribe-vocab:
	@test -n "$(FILE)" || (echo "Usage: make transcribe-vocab FILE=path/to/transcription.md" && exit 1)
	python scripts/transcribe_audio.py --vocab "$(FILE)"

# ─────────────────────────────────────────────────────────────────────────────
# thakk submodule
# ─────────────────────────────────────────────────────────────────────────────

thakk-update:
	git submodule update --remote --merge data/thakk
	@echo "thakk updated. Run 'make corpus' to rebuild."

thakk-push:
	@test -n "$(MSG)" || (echo "Usage: make thakk-push MSG=\"corpus: add word\"" && exit 1)
	cd data/thakk && git add -A && git commit -m "$(MSG)" && git push

# Alias
push-thakk: thakk-push
