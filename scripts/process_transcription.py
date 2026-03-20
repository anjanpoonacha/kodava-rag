#!/usr/bin/env python3
"""
Converts a raw audio transcription to a reviewed vocab table.

Usage:
    python scripts/process_transcription.py data/raw/transcriptions/new_session.txt

Output:
    data/processed/vocab_tables/new_session_vocab_table.md
    (human reviews this before running make corpus)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MODEL
import anthropic
from core.prompts import load_prompt

PROMPT = load_prompt("process_transcription")


def process(input_path: Path, output_path: Path):
    text = input_path.read_text(encoding="utf-8")
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=ANTHROPIC_BASE_URL,
    )
    r = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": PROMPT.format(text=text)}],
    )
    result = r.content[0].text
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"Written: {output_path}")
    print("Review this file before running: make corpus")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/process_transcription.py <transcription.txt>")
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"Not found: {src}")
        sys.exit(1)

    stem = src.stem.replace("_transcription", "")
    dest = ROOT / "data" / "processed" / "vocab_tables" / f"{stem}_vocab_table.md"
    process(src, dest)
