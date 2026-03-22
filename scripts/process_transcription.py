#!/usr/bin/env python3
"""
Converts a timestamped dual-language transcription to a 4-column vocab table.

The transcription must use the [MM:SS] / Kannada: / English: / --- format
produced by the kodava-quiz-transcriber agent.

Usage (legacy flat output):
    python scripts/process_transcription.py path/to/transcription.md

Usage (per-video directory — preferred):
    python scripts/process_transcription.py path/to/transcription.md \\
        --output-dir data/thakk/audio-vocab/sessions/session_04

Output:
    <output-dir>/vocab_table.md   (or legacy: data/processed/vocab_tables/<stem>_vocab_table.md)

Review the output file before running: python scripts/build_corpus.py
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, MODEL
import anthropic
from anthropic.types import TextBlock
from core.prompts import load_prompt

PROMPT = load_prompt("process_transcription")


def process(input_path: Path, output_path: Path) -> None:
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
    result = next(
        (b.text for b in r.content if isinstance(b, TextBlock)),
        "",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"Written: {output_path}")
    print("Review this file before running: python scripts/build_corpus.py")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcription", help="Path to transcription.md")
    parser.add_argument(
        "--output-dir",
        help="Per-video directory to write vocab_table.md into. "
        "Defaults to data/processed/vocab_tables/ (legacy).",
    )
    args = parser.parse_args()

    src = Path(args.transcription)
    if not src.exists():
        print(f"Not found: {src}")
        sys.exit(1)

    if args.output_dir:
        dest = Path(args.output_dir) / "vocab_table.md"
    else:
        stem = src.stem.replace("_transcription", "").replace("transcription", "")
        dest = ROOT / "data" / "processed" / "vocab_tables" / f"{stem}_vocab_table.md"

    process(src, dest)


if __name__ == "__main__":
    main()
