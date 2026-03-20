#!/usr/bin/env python3
import sys
from core.retriever import search_all
from core.llm import ask


def main():
    q = " ".join(sys.argv[1:]) or input("Query: ")
    ctx = search_all(q)
    print("\nContext hits:", len(ctx))
    print(ask(q, ctx))


if __name__ == "__main__":
    main()
