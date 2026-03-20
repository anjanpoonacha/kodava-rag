#!/usr/bin/env python3
"""Pre-warm BM25 index (optional — retriever lazy-loads on first query)"""

from core.retriever import search_all

search_all("test")
print("Index ready.")
