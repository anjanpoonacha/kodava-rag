from __future__ import annotations
import re
from pathlib import Path
from ingesters import BaseIngester, CorpusEntry, register

SKIP = {"english", "kodava takk", "kodava", "word", "phrase", "---", ""}

# Matches one markdown table cell — 2–120 chars between pipes
_CELL = r"\s*([^\|]{2,120}?)\s*"


def _cells(line: str) -> list[str]:
    """Return stripped cell values from a markdown table row, backtick-free."""
    parts = [c.strip().strip("`") for c in line.split("|")]
    return [p for p in parts if p]  # drop empty edge tokens


@register
class VocabTableIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return (
            path.suffix == ".md"
            and "vocab_table" in path.name
            and "_archive" not in path.parts
        )

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries = []
        text = path.read_text(encoding="utf-8")

        # Detect table width from the header row
        four_col = bool(re.search(r"\|\s*Kannada Script\s*\|", text, re.IGNORECASE))

        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cols = _cells(line)
            if len(cols) < 2:
                continue

            if four_col and len(cols) >= 4:
                # | English | Kodava Takk | Kannada Script | Explanation |
                english, kodava, kannada, explanation = (
                    cols[0],
                    cols[1],
                    cols[2],
                    cols[3],
                )
            elif len(cols) >= 3:
                # legacy 3-column: | English | Kodava Takk | Explanation |
                english, kodava, kannada, explanation = (cols[0], cols[1], "", cols[2])
            else:
                continue

            english = english.strip()
            kodava = kodava.strip()
            kannada = kannada.strip()
            explanation = explanation.strip()

            if english.lower().rstrip("-") in SKIP:
                continue
            if set(english.replace("-", "").replace(" ", "")) == set():
                continue
            if not kodava or set(kodava) <= set("- \t"):
                continue
            # Skip separator rows (---|--- etc.)
            if re.fullmatch(r"[-:| ]+", english):
                continue

            entries.append(
                CorpusEntry(
                    type="vocabulary",
                    kodava=kodava,
                    devanagari="",
                    kannada=kannada,
                    english=english,
                    explanation=explanation,
                    confidence="audio_source",
                    source=path.name,
                    tags=[],
                )
            )
        return entries
