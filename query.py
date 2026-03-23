#!/usr/bin/env python3
import asyncio
import sys
from core.retriever import search_all_async
from core.llm import ask


async def main():
    q = " ".join(sys.argv[1:]) or input("Query: ")
    ctx = await search_all_async(q)
    print("\nContext hits:", len(ctx))
    print(ask(q, ctx))


if __name__ == "__main__":
    asyncio.run(main())
