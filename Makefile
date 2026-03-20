.PHONY: install corpus query api

install:
	pip install -r requirements.txt
	pip install -e .

corpus:
	python scripts/build_corpus.py

query:
	python query.py $(ARGS)

api:
	python3 -m uvicorn api.app:app --reload
