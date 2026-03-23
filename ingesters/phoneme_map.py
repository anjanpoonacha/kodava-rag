"""Ingester for the Kodava phoneme map Markdown table.

Reads data/thakk/phoneme_table/kodava_devanagari_map.md and produces
CorpusEntry objects for every phoneme row and every case suffix row.

The file uses section headings (## Vowels, ## Consonants, etc.) followed by
Markdown tables. Each section is parsed into phoneme entries; ## Case Suffixes
produces suffix_rule entries. All other sections (Stem Change Rules, Verb
Rules) are ignored by the corpus ingester — they are reference tables for
human readers and the generate_phoneme_rules.py generator.
"""

from __future__ import annotations

import re
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

# Section headings that produce phoneme corpus entries
_PHONEME_SECTIONS = {
    "Vowels": "vowel",
    "Consonants": "consonant",
    "Retroflex Consonants": "retroflex",
    "Geminates": "geminate",
}

_SUFFIX_SECTION = "Case Suffixes"

_CONFIDENCE_MAP = {
    "✅": "verified",
    "⚠️": "unverified",
    "🔴": "unverified",
    "🟡": "unverified",
}


def _parse_table(lines: list[str]) -> list[dict[str, str]]:
    """Parse a Markdown table into a list of dicts keyed by header name."""
    headers: list[str] = []
    rows: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not headers:
            headers = [h.lower() for h in cells]
            continue
        if all(re.match(r"^[-: ]+$", c) for c in cells):
            continue
        row = dict(zip(headers, cells))
        rows.append(row)
    return rows


def _confidence(raw: str) -> str:
    for flag, level in _CONFIDENCE_MAP.items():
        if flag in raw:
            return level
    return "unverified"


@register
class PhonemeMapIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".md" and "devanagari_map" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries: list[CorpusEntry] = []
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        current_section: str | None = None
        section_lines: list[str] = []

        def _flush(section: str, buf: list[str]) -> None:
            if section in _PHONEME_SECTIONS:
                _ingest_phoneme_section(section, buf, entries, path.name)
            elif section == _SUFFIX_SECTION:
                _ingest_suffix_section(buf, entries, path.name)

        for line in lines:
            heading = re.match(r"^##\s+(.+)", line)
            if heading:
                if current_section:
                    _flush(current_section, section_lines)
                current_section = heading.group(1).strip()
                section_lines = []
            else:
                section_lines.append(line)

        if current_section:
            _flush(current_section, section_lines)

        return entries


def _ingest_phoneme_section(
    section: str, lines: list[str], entries: list[CorpusEntry], source: str
) -> None:
    phoneme_type_prefix = _PHONEME_SECTIONS.get(section, section.lower())
    for row in _parse_table(lines):
        kodava = row.get("kodava", "").strip()
        if not kodava:
            continue
        raw_conf = row.get("confidence", "⚠️")
        ptype = row.get("type", phoneme_type_prefix).strip()
        note = row.get("note", "").strip()
        flag = row.get("flag / note", row.get("flag", "")).strip()
        explanation = note or flag

        entries.append(
            CorpusEntry(
                type="phoneme",
                kodava=kodava,
                devanagari=row.get("devanagari", "").strip(),
                kannada=row.get("kannada", "").strip(),
                english=row.get("sound hint", "").strip(),
                explanation=explanation,
                confidence=_confidence(raw_conf),
                source=source,
                tags=[f"phoneme_type:{ptype}"],
            )
        )


def _ingest_suffix_section(
    lines: list[str], entries: list[CorpusEntry], source: str
) -> None:
    for row in _parse_table(lines):
        suffix = row.get("suffix", "").strip()
        if not suffix:
            continue
        raw_conf = row.get("confidence", "⚠️")
        flag = row.get("flag", "").strip()
        example = row.get("example", "").strip()
        explanation = flag
        if example:
            explanation = f"{flag} e.g. {example}".strip()

        entries.append(
            CorpusEntry(
                type="phoneme",
                kodava=suffix,
                devanagari=row.get("devanagari", "").strip(),
                kannada=row.get("kannada", "").strip(),
                english=row.get("meaning", "").strip(),
                explanation=explanation,
                confidence=_confidence(raw_conf),
                source=source,
                tags=["suffix_rule"],
            )
        )
