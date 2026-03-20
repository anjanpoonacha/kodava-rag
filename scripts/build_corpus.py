#!/usr/bin/env python3
"""Compiles source/ → data/corpus/*.jsonl"""

import json, re
from pathlib import Path
from config import SOURCE, DATA

OUT = DATA / "corpus"
OUT.mkdir(parents=True, exist_ok=True)


def write(name, entries):
    p = OUT / f"{name}.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"  {name}.jsonl: {len(entries)}")


def build_grammar_rules():
    f = SOURCE / "corrections" / "kodava_corrections.md"
    if not f.exists():
        return []
    text = f.read_text(encoding="utf-8")
    entries = []
    blocks = re.split(r"\n- WHAT:", text)
    for i, b in enumerate(blocks[1:], 1):
        correct = re.search(r"- CORRECT:\s*(.+)", b)
        entries.append(
            {
                "id": f"r{i:03d}",
                "type": "grammar_rule",
                "wrong": b.split("\n")[0].strip(),
                "correct": correct.group(1).strip() if correct else "",
                "source": "corrections.md",
            }
        )
    return entries


def build_vocabulary():
    entries = []
    for md in (SOURCE / "audio" / "vocab_tables").glob("*.md"):
        rows = re.findall(
            r"\|\s*([^\|]{3,40})\s*\|\s*([^\|]{3,60})\s*\|\s*([^\|]*)\s*\|",
            md.read_text(),
        )
        for i, (en, ko, ex) in enumerate(rows):
            if en.strip().lower() in ("english", "---", "") or "-" in en[:3]:
                continue
            entries.append(
                {
                    "id": f"v_{md.stem}_{i:03d}",
                    "type": "vocabulary",
                    "english": en.strip(),
                    "kodava": ko.strip(),
                    "explanation": ex.strip(),
                    "source": md.name,
                }
            )
    return entries


if __name__ == "__main__":
    print("Building corpus...")
    write("vocabulary", build_vocabulary())
    write("grammar_rules", build_grammar_rules())
    sentences_path = OUT / "sentences.jsonl"
    if not sentences_path.exists():
        sentences_path.touch()
        print("  sentences.jsonl: 0 (created)")
    else:
        count = sum(
            1 for line in sentences_path.read_text().splitlines() if line.strip()
        )
        print(f"  sentences.jsonl: {count} (preserved)")
    print("Done.")
