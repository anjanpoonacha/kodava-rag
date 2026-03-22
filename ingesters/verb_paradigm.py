"""Ingester for verb_paradigms.md — full person×tense paradigm tables.

File format
-----------
## VerbInfinitive — meaning

### Tense name

| Person | Kodava | Kannada | Notes |
|--------|--------|---------|-------|
| naan (I) | form | script | flag |
...

One grammar_rule corpus entry is emitted per (verb, tense) block.
The kodava field holds the naan (1st person singular) form.
The explanation field holds a compact pipe-delimited table of all six forms
suitable for both BM25 retrieval and dense embedding.
"""

from __future__ import annotations

import re
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

_VERB_RE = re.compile(r"^##\s+(\S+)\s+—\s+(.+)$")
_TENSE_RE = re.compile(r"^###\s+(.+)$")
_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|")

# Maps person cell prefixes to canonical short labels
_PERSON_MAP = {
    "naan": "naan",
    "niin": "niin",
    "āāwu": "āāwu",
    "aawu": "āāwu",
    "nanga": "nanga",
    "ninga": "ninga",
    "ainga": "ainga",
}

# Header rows to skip
_SKIP_ROWS = frozenset({"person", "---", ""})


def _parse_person(cell: str) -> str | None:
    """Extract the canonical person label from a table row's first cell."""
    key = cell.strip().lower().split("(")[0].strip()
    return _PERSON_MAP.get(key)


@register
class VerbParadigmIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".md" and "verb_paradigm" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries: list[CorpusEntry] = []
        text = path.read_text(encoding="utf-8")

        current_verb = ""
        current_meaning = ""
        current_tense = ""
        rows: list[tuple[str, str, str]] = []  # (person, kodava, kannada)

        def flush() -> None:
            if not current_verb or not current_tense or not rows:
                return
            naan_kodava = ""
            naan_kannada = ""
            parts: list[str] = []
            for person, kodava, kannada in rows:
                parts.append(f"{person}: {kodava}")
                if person == "naan":
                    naan_kodava = kodava
                    naan_kannada = kannada

            if not naan_kodava:
                # Fall back to first row if naan not found
                naan_kodava = rows[0][1]
                naan_kannada = rows[0][2]

            explanation = (
                f"{current_verb} ({current_meaning}) — {current_tense} tense. "
                + " | ".join(parts)
            )

            # Use source filename as disambiguator in english so this entry
            # gets a distinct ID from any matching conjugations.jsonl entry,
            # allowing both to coexist in the corpus with complementary tags.
            entries.append(
                CorpusEntry(
                    type="grammar_rule",
                    kodava=naan_kodava,
                    devanagari="",
                    kannada=naan_kannada,
                    english=f"{current_tense} tense of {current_verb} — {current_meaning} [paradigm]",
                    explanation=explanation[:800],
                    confidence="verified",
                    source=path.name,
                    tags=[
                        f"verb:{current_verb}",
                        f"tense:{current_tense.lower().replace(' ', '_')}",
                        "paradigm",
                    ],
                )
            )

        for line in text.splitlines():
            verb_m = _VERB_RE.match(line)
            if verb_m:
                flush()
                rows = []
                current_verb = verb_m.group(1).strip()
                current_meaning = verb_m.group(2).strip()
                current_tense = ""
                continue

            tense_m = _TENSE_RE.match(line)
            if tense_m:
                flush()
                rows = []
                current_tense = tense_m.group(1).strip()
                continue

            row_m = _ROW_RE.match(line)
            if row_m and current_verb and current_tense:
                person_raw = row_m.group(1).strip()
                kodava = row_m.group(2).strip()
                kannada = row_m.group(3).strip()

                if person_raw.lower().replace("-", "").strip() in _SKIP_ROWS:
                    continue
                if not kodava or set(kodava) <= {"-", " ", "\t"}:
                    continue

                person = _parse_person(person_raw)
                if person is None:
                    continue

                rows.append((person, kodava, kannada))

        flush()
        return entries
