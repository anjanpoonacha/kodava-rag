"""Ingester for pre-built JSONL files synced from thakk/corpus/.

Reads vocabulary.jsonl, grammar_rules.jsonl, and phonemes.jsonl that were
curated and exported from the thakk repo. Each line is already a fully-formed
corpus entry — fields are passed through as-is, including the original ID so
that named seeds (core_0001, greet_0001, etc.) and short-hash IDs are preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

_HANDLED = frozenset(
    {"vocabulary.jsonl", "grammar_rules.jsonl", "phonemes.jsonl", "sentences.jsonl"}
)

_TYPE_MAP = {
    "vocabulary.jsonl": "vocabulary",
    "grammar_rules.jsonl": "grammar_rule",
    "phonemes.jsonl": "phoneme",
    "sentences.jsonl": "sentence",
}


class _PassthroughEntry(CorpusEntry):
    """CorpusEntry that preserves the original ID from the source file."""

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


@register
class CorpusJsonlIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.parent.name == "corpus" and path.name in _HANDLED

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries: list[CorpusEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue

            kodava = (e.get("kodava") or "").strip()
            if not kodava:
                continue

            entries.append(
                _PassthroughEntry(
                    original_id=e.get("id") or "",
                    type=e.get("type") or _TYPE_MAP[path.name],
                    kodava=kodava,
                    devanagari=e.get("devanagari") or "",
                    kannada=e.get("kannada") or "",
                    english=e.get("english") or "",
                    explanation=e.get("explanation") or "",
                    confidence=e.get("confidence") or "unverified",
                    source=e.get("source") or path.name,
                    tags=e.get("tags") or [],
                )
            )
        return entries
