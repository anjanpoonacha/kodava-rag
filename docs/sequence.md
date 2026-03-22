# Kodava RAG — Sequence Diagrams

## Diagram 1: User Query Flow

Shows the full lifecycle of a `POST /query` or `/agent/stream` request: OAuth2 JWT authentication,
multi-turn Claude tool-use loop, hybrid BM25 + dense retrieval, and response delivery.

```mermaid
sequenceDiagram
    autonumber

    participant Browser
    participant Approuter as Approuter<br/>(OAuth2 / JWT)
    participant FastAPI as FastAPI<br/>(lingua-api:8000)
    participant AgentLoop as AgentLoop<br/>(core/agent.py)
    participant GitHub as GitHub<br/>(raw.githubusercontent.com)
    participant BM25Engine as BM25Engine<br/>(core/retriever.py)
    participant VectorIndex as VectorIndex<br/>(core/vector_index.py)
    participant EmbedAPI as EmbedAPI<br/>(ai-proxy:3030)
    participant Claude as Claude<br/>(via ai-proxy → LLM backend)

    Browser->>Approuter: POST /query + JWT token
    Approuter->>Approuter: Validate JWT
    Approuter->>FastAPI: Forward request (validated identity)

    FastAPI->>AgentLoop: run_with_trace(query)

    rect rgb(230, 240, 255)
        Note over AgentLoop,GitHub: Prompt loading — fresh on every call
        AgentLoop->>GitHub: GET prompts/rag_assistant.md
        GitHub-->>AgentLoop: System prompt text
        AgentLoop->>GitHub: GET prompts/search_agent.md
        GitHub-->>AgentLoop: Tool description text
    end

    rect rgb(230, 255, 230)
        Note over AgentLoop,Claude: Agent tool-use loop (may iterate 1–N times)

        AgentLoop->>Claude: messages.create(system=rag_assistant,<br/>tools=[search_kodava], messages=[user query])
        Claude-->>AgentLoop: stop_reason=tool_use<br/>tool_input={query:"cook cooking", collection:"vocabulary"}

        rect rgb(255, 250, 220)
            Note over AgentLoop,VectorIndex: search_all_async — BM25 + dense, run in parallel
            AgentLoop->>BM25Engine: search("cook cooking", "vocabulary")<br/>Layer 1: phrase BM25 · Layer 2: token voting
            BM25Engine-->>AgentLoop: top-5 vocabulary docs (confidence re-ranked)

            AgentLoop->>EmbedAPI: embed_one("cook cooking")
            EmbedAPI-->>AgentLoop: query vector (3072-d float32)
            AgentLoop->>VectorIndex: search(query_vec, top_k=12) cosine similarity
            VectorIndex-->>AgentLoop: dense top-12 docs

            AgentLoop->>AgentLoop: _rrf_merge(bm25_results, dense_results, k=60)
        end

        AgentLoop->>Claude: tool_result [merged JSON docs]
        Claude-->>AgentLoop: stop_reason=tool_use<br/>tool_input={query:"how manner", collection:"vocabulary"}

        rect rgb(255, 250, 220)
            Note over AgentLoop,VectorIndex: Second search — cross-collection
            AgentLoop->>BM25Engine: search("how manner", "vocabulary")
            BM25Engine-->>AgentLoop: ennane entry + related docs

            AgentLoop->>EmbedAPI: embed_one("how manner")
            EmbedAPI-->>AgentLoop: query vector (3072-d float32)
            AgentLoop->>VectorIndex: search(query_vec, top_k=12)
            VectorIndex-->>AgentLoop: dense top-12 docs

            AgentLoop->>AgentLoop: _rrf_merge(bm25_results, dense_results, k=60)
        end

        AgentLoop->>Claude: tool_result [merged JSON docs]
        Claude-->>AgentLoop: stop_reason=end_turn<br/>answer: "ennane adige maaduva …"
    end

    AgentLoop-->>FastAPI: AgentTrace{answer, search_calls, context}
    FastAPI-->>Approuter: {answer, context, search_calls} JSON
    Approuter-->>Browser: HTTP 200 JSON response
```

---

## Diagram 2: Startup / Corpus Build Flow

Shows container startup: optional `thakk` clone, full corpus ingestion pipeline, conditional
embedding generation (skipped when corpus hash is unchanged), and FastAPI initialisation.

```mermaid
sequenceDiagram
    autonumber

    participant Entrypoint as entrypoint.sh
    participant GitHubClone as GitHubClone<br/>(git clone anjanpoonacha/thakk)
    participant BuildCorpus as BuildCorpus<br/>(scripts/build_corpus.py)
    participant Ingesters as Ingesters<br/>(ingesters/)
    participant EmbedAPI as EmbedAPI<br/>(ai-proxy:3030)
    participant Uvicorn as Uvicorn<br/>(api/app.py)
    participant GitHub as GitHub<br/>(raw.githubusercontent.com)

    Entrypoint->>Entrypoint: Start — check data/thakk present

    alt data/thakk absent
        Entrypoint->>GitHubClone: git clone --depth 1 anjanpoonacha/thakk data/thakk
        GitHubClone-->>Entrypoint: corpus files ready
    else data/thakk present
        Note over Entrypoint: Skip clone — use existing submodule checkout
    end

    Entrypoint->>BuildCorpus: python scripts/build_corpus.py

    rect rgb(230, 240, 255)
        Note over BuildCorpus,Ingesters: Pass 1 — curated JSONL (passthrough, preserves IDs)
        BuildCorpus->>Ingesters: CorpusJsonlIngester<br/>(corpus/*.jsonl)
        Ingesters-->>BuildCorpus: vocabulary, grammar_rules, phonemes, sentences records
    end

    rect rgb(230, 255, 230)
        Note over BuildCorpus,Ingesters: Pass 2 — derived sources
        BuildCorpus->>Ingesters: VocabTableIngester (*vocab_table*.md)
        BuildCorpus->>Ingesters: CorrectionsIngester (*corrections*.md)
        BuildCorpus->>Ingesters: PhonemeMapIngester (*devanagari_map*.json)
        BuildCorpus->>Ingesters: ElementaryKodavaIngester (elementary_kodava_FINAL.md)
        Ingesters-->>BuildCorpus: merged records (first-match-wins dedup)
    end

    BuildCorpus->>BuildCorpus: Write vocabulary.jsonl, grammar_rules.jsonl,<br/>phonemes.jsonl, sentences.jsonl

    BuildCorpus->>BuildCorpus: Split sentences →<br/>sentences_lesson.jsonl + sentences_narrative.jsonl

    BuildCorpus->>BuildCorpus: Compute SHA-256 corpus hash (all output JSONL)

    BuildCorpus->>BuildCorpus: Read embeddings_meta.json corpus_hash

    alt corpus hash changed (or embeddings absent)
        BuildCorpus->>EmbedAPI: embed_batch(3284 docs, batch_size=200)<br/>17 sequential API calls
        EmbedAPI-->>BuildCorpus: (3284, 3072) float32 matrix
        BuildCorpus->>BuildCorpus: Write embeddings.npy + embeddings_meta.json
    else corpus hash unchanged
        Note over BuildCorpus: Skip embedding — reuse cached embeddings.npy
    end

    BuildCorpus-->>Entrypoint: Corpus build complete

    Entrypoint->>Uvicorn: uvicorn api.app:app --host 0.0.0.0 --port 8000

    rect rgb(255, 250, 220)
        Note over Uvicorn,GitHub: Application startup hooks
        Uvicorn->>GitHub: load_prompt("rag_assistant")<br/>(PROMPT_FETCH=true)
        GitHub-->>Uvicorn: prompts/rag_assistant.md text
        Note over Uvicorn: Log: "prompt loaded from github"
        Uvicorn->>Uvicorn: load_vector_index()<br/>np.load(embeddings.npy) → VectorIndex instance
        Note over Uvicorn: Log: "vector index ready — 3284 docs"
    end

    Uvicorn-->>Entrypoint: Application startup complete
```
