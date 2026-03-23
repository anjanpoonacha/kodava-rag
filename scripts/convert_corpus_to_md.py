#!/usr/bin/env python3
"""One-time migration: convert data/thakk/corpus/*.jsonl to Markdown table format.

Reads each curated JSONL file and writes a corresponding .md file in the same
directory. The .md files are the new source-of-truth format; the .jsonl files
can be deleted after verifying the build output is identical.

Usage:
    python scripts/convert_corpus_to_md.py [--dry-run]

The --dry-run flag prints what would be written without touching any files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "data" / "thakk" / "corpus"

# Column layout per file: (header label, field key, width_hint)
# width_hint is the minimum column width for alignment (purely cosmetic).
_LAYOUTS: dict[str, list[tuple[str, str, int]]] = {
    "vocabulary": [
        ("ID", "id", 12),
        ("Kodava", "kodava", 24),
        ("Kannada", "kannada", 18),
        ("Devanagari", "devanagari", 14),
        ("English", "english", 40),
        ("Explanation", "explanation", 50),
        ("Confidence", "confidence", 12),
        ("Tags", "tags", 20),
    ],
    "grammar_rules": [
        ("ID", "id", 10),
        ("Kodava", "kodava", 30),
        ("Kannada", "kannada", 30),
        ("Devanagari", "devanagari", 14),
        ("English", "english", 50),
        ("Explanation", "explanation", 60),
        ("Confidence", "confidence", 12),
        ("Tags", "tags", 12),
    ],
    "phonemes": [
        ("ID", "id", 10),
        ("Kodava", "kodava", 8),
        ("Kannada", "kannada", 8),
        ("Devanagari", "devanagari", 12),
        ("Sound hint", "english", 50),
        ("Explanation", "explanation", 40),
        ("Confidence", "confidence", 12),
        ("Tags", "tags", 28),
    ],
    "sentences": [
        ("ID", "id", 16),
        ("Type", "type", 10),
        ("Kodava", "kodava", 40),
        ("Kannada", "kannada", 30),
        ("English", "english", 50),
        ("Explanation", "explanation", 50),
        ("Query", "query", 30),
        ("Note", "note", 40),
        ("Confidence", "confidence", 12),
        ("Status", "status", 9),
        ("Source", "source", 18),
        ("Tags", "tags", 20),
    ],
}

_TITLES = {
    "vocabulary": "Kodava Vocabulary — Curated",
    "grammar_rules": "Kodava Grammar Rules — Curated",
    "phonemes": "Kodava Phonemes — Curated",
    "sentences": "Kodava Sentences — Curated",
}


def _escape(value: str) -> str:
    """Escape pipe characters inside a cell value."""
    return value.replace("|", "\\|")


def _tags_str(tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, list):
        return ", ".join(tags)
    return str(tags)


def _cell(value: str, width: int) -> str:
    """Return a cell padded to at least `width` characters."""
    escaped = _escape(str(value))
    if len(escaped) >= width:
        return escaped
    return escaped + " " * (width - len(escaped))


def convert_file(src: Path, dry_run: bool = False) -> Path:
    stem = src.stem  # e.g. "vocabulary"
    layout = _LAYOUTS.get(stem)
    if layout is None:
        print(f"  SKIP {src.name}: no layout defined")
        return src

    entries = []
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    headers = [label for label, _, _ in layout]
    widths = [max(w, len(label)) for label, _, w in layout]

    # Adjust widths based on actual content
    for entry in entries:
        for i, (_, field, _) in enumerate(layout):
            if field == "tags":
                val = _tags_str(entry.get(field, ""))
            else:
                val = str(entry.get(field, "") or "")
            widths[i] = max(widths[i], len(_escape(val)))

    lines: list[str] = []
    title = _TITLES.get(stem, stem)
    lines.append(f"# {title}")
    lines.append("")

    # Header row
    header_row = (
        "| " + " | ".join(_cell(h, widths[i]) for i, h in enumerate(headers)) + " |"
    )
    sep_row = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    lines.append(header_row)
    lines.append(sep_row)

    for entry in entries:
        cells = []
        for i, (_, field, _) in enumerate(layout):
            if field == "tags":
                val = _tags_str(entry.get(field, ""))
            else:
                val = str(entry.get(field, "") or "")
            cells.append(_cell(val, widths[i]))
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    content = "\n".join(lines)

    dest = src.with_suffix(".md")
    if dry_run:
        print(
            f"  DRY-RUN would write {dest.relative_to(ROOT)} ({len(entries)} entries)"
        )
        print(lines[0])
        print(lines[2][:120] + ("..." if len(lines[2]) > 120 else ""))
        print()
    else:
        dest.write_text(content, encoding="utf-8")
        print(f"  wrote {dest.relative_to(ROOT)} ({len(entries)} entries)")

    return dest


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    stems_to_convert = ["vocabulary", "grammar_rules", "phonemes", "sentences"]
    found = 0
    for stem in stems_to_convert:
        src = CORPUS / f"{stem}.jsonl"
        if not src.exists():
            print(f"  MISSING {src.name} — skipping")
            continue
        found += 1
        convert_file(src, dry_run=dry_run)

    if not found:
        print("No JSONL files found in", CORPUS)
        sys.exit(1)

    if not dry_run:
        print()
        print("Done. Verify the build output with:")
        print("  python scripts/build_corpus.py")
        print("Then delete the old JSONL files:")
        print("  (cd data/thakk && git rm corpus/*.jsonl)")


if __name__ == "__main__":
    main()
