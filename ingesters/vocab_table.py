from __future__ import annotations
import re
from pathlib import Path
from ingesters import BaseIngester, CorpusEntry, register

SKIP = {"english", "kodava takk", "kodava", "word", "phrase", "---", ""}


@register
class VocabTableIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".md" and "vocab_table" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries = []
        text = path.read_text(encoding="utf-8")
        rows = re.findall(
            r"\|\s*([^\|]{2,80})\s*\|\s*([^\|]{2,80})\s*\|\s*([^\|]*)\s*\|",
            text,
        )
        for english, kodava, explanation in rows:
            english = english.strip()
            kodava = kodava.strip()
            explanation = explanation.strip()

            if english.lower().rstrip("-") in SKIP:
                continue
            if set(english.replace("-", "").replace(" ", "")) == set():
                continue

            if not kodava or set(kodava) <= set("- \t"):
                continue

            entries.append(
                CorpusEntry(
                    type="vocabulary",
                    kodava=kodava,
                    devanagari="",
                    kannada="",
                    english=english,
                    explanation=explanation,
                    confidence="audio_source",
                    source=path.name,
                    tags=[],
                )
            )
        return entries
