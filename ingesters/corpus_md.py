"""Ingester for curated corpus Markdown tables in data/thakk/corpus/*.md.

Each file is a single Markdown table where the header row defines the columns.
Column names are matched case-insensitively to CorpusEntry fields. The original
ID is preserved via _PassthroughEntry so named seeds (greet_0001, etc.) and
short-hash IDs remain stable across builds.

Supported files: vocabulary.md, grammar_rules.md, phonemes.md, sentences.md,
                 feedback_pending.md
"""

from __future__ import annotations

import re
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

_HANDLED_STEMS = frozenset(
    {"vocabulary", "grammar_rules", "phonemes", "sentences", "feedback_pending"}
)

_TYPE_MAP = {
    "vocabulary": "vocabulary",
    "grammar_rules": "grammar_rule",
    "phonemes": "phoneme",
    "sentences": "sentence",
    "feedback_pending": "sentence",
}

# Map lowercase column header variants → CorpusEntry field name
_COL_MAP = {
    "id": "id",
    "type": "type",
    "kodava": "kodava",
    "kodava takk": "kodava",
    "devanagari": "devanagari",
    "kannada": "kannada",
    "kannada script": "kannada",
    "english": "english",
    "sound hint": "english",
    "explanation": "explanation",
    "confidence": "confidence",
    "source": "source",
    "tags": "tags",
    # sentences extras
    "query": "query",
    "note": "note",
    "status": "status",
}


class _PassthroughEntry(CorpusEntry):
    """Preserves the original ID from the source file."""

    def __init__(self, original_id: str, **kwargs):
        super().__init__(**kwargs)
        self._original_id = original_id

    @property
    def id(self) -> str:
        return self._original_id or super().id

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["id"] = self.id
        return d


def _parse_row(line: str) -> list[str]:
    """Split a markdown table row into trimmed cell values."""
    # Strip leading/trailing pipe, split on |, trim each cell
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator(line: str) -> bool:
    """Return True for lines like |---|---| (table separator rows)."""
    return bool(re.match(r"^\s*\|[-: |]+\|\s*$", line))


def _parse_tags(raw: str) -> list[str]:
    """Parse a comma-separated or space-separated tags string."""
    raw = raw.strip()
    if not raw:
        return []
    # Support both comma and space separation
    parts = [t.strip() for t in re.split(r"[,;]+", raw) if t.strip()]
    return parts


@register
class CorpusMdIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return (
            path.suffix == ".md"
            and path.parent.name == "corpus"
            and path.stem in _HANDLED_STEMS
        )

    def ingest(self, path: Path) -> list[CorpusEntry]:
        default_type = _TYPE_MAP.get(path.stem, "vocabulary")
        entries: list[CorpusEntry] = []
        columns: list[str] = []  # field names in column order

        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()

            # Skip empty lines and non-table lines (headings, prose)
            if not stripped or not stripped.startswith("|"):
                continue

            # Separator row
            if _is_separator(stripped):
                continue

            cells = _parse_row(stripped)

            # Header row — discover columns
            if not columns:
                columns = [_COL_MAP.get(c.lower(), c.lower()) for c in cells]
                continue

            # Data row — zip cells with column names
            row: dict[str, str] = {}
            for col, val in zip(columns, cells):
                row[col] = val

            kodava = row.get("kodava", "").strip()
            if not kodava:
                continue

            entry_type = row.get("type", "").strip() or default_type
            tags_raw = row.get("tags", "")
            tags = _parse_tags(tags_raw)

            entries.append(
                _PassthroughEntry(
                    original_id=row.get("id", "").strip(),
                    type=entry_type,
                    kodava=kodava,
                    devanagari=row.get("devanagari", "").strip(),
                    kannada=row.get("kannada", "").strip(),
                    english=row.get("english", "").strip(),
                    explanation=row.get("explanation", "").strip(),
                    confidence=row.get("confidence", "unverified").strip()
                    or "unverified",
                    source=row.get("source", "").strip() or path.name,
                    tags=tags,
                )
            )

        return entries
