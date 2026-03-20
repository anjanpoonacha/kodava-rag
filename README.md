# kodava-rag

RAG system for Kodava takk language queries.

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env  # add ANTHROPIC_API_KEY
python scripts/build_corpus.py
```

## Run
```bash
# CLI
python query.py how do I say good morning

# API
uvicorn api.app:app --reload
```

## Architecture
```mermaid
graph TD
    Q[Query] --> API[FastAPI]
    API --> BM25[BM25 Search]
    BM25 --> LLM[Claude Sonnet 4.6]
    LLM --> R[Response]

    FB[User Feedback] --> API
    API -->|approved/corrected| S[sentences.jsonl]
    API -->|rejected| RV[review.jsonl]
    S --> BM25

    SRC[source/] -->|build_corpus.py| CRP[data/corpus/]
    CRP --> BM25
```

## Data
- `source/` — human truth, edit here
- `data/corpus/` — auto-built, do not edit
- `data/corpus/sentences.jsonl` — add verified pairs here

## Add a sentence
```bash
echo '{"id":"s001","kodava":"naan poanê.","devanagari":"नान पोअनॅ.","english":"I went."}' >> data/corpus/sentences.jsonl
```
