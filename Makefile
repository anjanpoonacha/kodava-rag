.PHONY: install corpus query api process sync

install:
	pip install -r requirements.txt
	pip install -e .

corpus:
	python scripts/build_corpus.py

process:
	python scripts/process_transcription.py $(FILE)

query:
	python query.py $(ARGS)

api:
	python3 -m uvicorn api.app:app --reload

sync:
	./scripts/sync.sh $(MSG)

