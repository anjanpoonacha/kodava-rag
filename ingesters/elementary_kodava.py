"""Ingester for elementary_kodava_FINAL.md — a 16-lesson Kodava textbook.

Extracts three entry types:
  vocabulary   — rows from | kodava | English | tables in VOCABULARY sections
  grammar_rule — prose blocks under EXPLANATION / Grammatical Explanation sections
  sentence     — dialogue lines from SAMPLE CONVERSATION / Sample Dialogue tables
"""

from __future__ import annotations

import re
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

# Matches any lesson header and captures the lesson number
_LESSON_RE = re.compile(r"^#+ (?:LESSON|Lesson)\s+(\d+)\b", re.IGNORECASE)

# Matches a markdown table row with at least 2 non-empty cells
_ROW_RE = re.compile(r"^\|\s*([^\|]{1,120}?)\s*\|\s*([^\|]{1,120}?)\s*\|")

# Section heading keywords that introduce vocabulary tables
_VOCAB_SECTION_RE = re.compile(
    r"^#+.*\*{0,2}(VOCABULARY|Vocabulary|IMPORTANT PHRASES)\*{0,2}", re.IGNORECASE
)

# Section heading keywords that introduce grammar explanations
_GRAMMAR_SECTION_RE = re.compile(
    r"^#+.*\*{0,2}(EXPLANATION|GRAMMATICAL EXPLANATION|Grammatical Explanation)\*{0,2}",
    re.IGNORECASE,
)

# Section heading keywords that introduce sample conversations / dialogues
_CONV_SECTION_RE = re.compile(
    r"^#+.*\*{0,2}(SAMPLE CONVERSATION|Sample Dialogue)\*{0,2}", re.IGNORECASE
)

# Rows to skip — header-like or separator content
_SKIP_CELLS: frozenset[str] = frozenset(
    {
        "",
        "-",
        "---",
        "kodava",
        "english",
        "kodava takk",
        "word",
        "phrase",
        "kodava takk / romanization",
        "romanization",
        "translation",
    }
)

# Minimum plausible Kodava content length
_MIN_LEN = 2


def _is_skip(cell: str) -> bool:
    return cell.lower().rstrip("-. ") in _SKIP_CELLS or len(cell) < _MIN_LEN


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).strip("*_")


class _Section:
    NONE = "none"
    VOCAB = "vocab"
    GRAMMAR = "grammar"
    CONV = "conv"


@register
class ElementaryKodavaIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.name == "elementary_kodava_FINAL.md"

    def ingest(self, path: Path) -> list[CorpusEntry]:
        lines = path.read_text(encoding="utf-8").splitlines()
        entries: list[CorpusEntry] = []
        current_lesson = 0
        section = _Section.NONE
        grammar_buf: list[str] = []
        grammar_section_title = ""

        def flush_grammar() -> None:
            if not grammar_buf:
                return
            text = " ".join(grammar_buf).strip()
            if len(text) < 20:
                return
            # Extract a short kodava key term from the first sentence
            first = grammar_buf[0]
            # Look for a bold or italic term
            m = re.search(r"\*{1,2}([a-zA-Z'ê\-]{2,30})\*{1,2}", first)
            kodava_key = m.group(1) if m else grammar_section_title[:40]
            entries.append(
                CorpusEntry(
                    type="grammar_rule",
                    kodava=kodava_key or grammar_section_title[:40],
                    devanagari="",
                    kannada="",
                    english=grammar_section_title,
                    explanation=text[:600],
                    confidence="textbook",
                    source=path.name,
                    tags=[f"lesson:{current_lesson}"] if current_lesson else [],
                )
            )
            grammar_buf.clear()

        for raw_line in lines:
            line = raw_line.rstrip()

            # Track lesson number
            lm = _LESSON_RE.match(line)
            if lm:
                flush_grammar()
                current_lesson = int(lm.group(1))
                section = _Section.NONE
                continue

            # Section transitions
            if _VOCAB_SECTION_RE.match(line):
                flush_grammar()
                section = _Section.VOCAB
                continue
            if _GRAMMAR_SECTION_RE.match(line):
                flush_grammar()
                section = _Section.GRAMMAR
                grammar_section_title = _clean(re.sub(r"^#+\s*", "", line).strip("*_ "))
                continue
            if _CONV_SECTION_RE.match(line):
                flush_grammar()
                section = _Section.CONV
                continue

            # Other headings reset section (don't flush grammar — sub-sections are ok)
            if re.match(r"^#{1,4}\s+", line) and not re.match(r"^#{5,}", line):
                flush_grammar()
                section = _Section.NONE
                continue

            # Page comments and footnotes — skip
            if line.startswith("<!--") or re.match(r"^[⁰¹²³⁴⁵⁶⁷⁸⁹\d]+\s", line):
                continue

            tags = [f"lesson:{current_lesson}"] if current_lesson else []

            if section == _Section.VOCAB:
                m = _ROW_RE.match(line)
                if not m:
                    continue
                cell_a, cell_b = _clean(m.group(1)), _clean(m.group(2))
                if _is_skip(cell_a) or _is_skip(cell_b):
                    continue
                # Table orientation: col1=kodava col2=english OR col1=english col2=kodava
                # In LESSON 1+: | kodava | English | — kodava is col1
                # In LESSON 9 style: | | | — first cell may be empty phrase
                # Heuristic: if col1 looks like an English sentence (starts uppercase,
                # contains spaces and common words) treat col2 as kodava.
                kodava, english = _orient(cell_a, cell_b)
                if not kodava:
                    continue
                entries.append(
                    CorpusEntry(
                        type="vocabulary",
                        kodava=kodava,
                        devanagari="",
                        kannada="",
                        english=english,
                        explanation="",
                        confidence="textbook",
                        source=path.name,
                        tags=tags,
                    )
                )

            elif section == _Section.GRAMMAR:
                # Accumulate prose lines; skip table rows and separators
                if line.startswith("|") or line.startswith("---") or not line.strip():
                    # Inline tables within grammar sections → treat as examples, skip
                    continue
                stripped = line.strip()
                if stripped:
                    grammar_buf.append(stripped)

            elif section == _Section.CONV:
                m = _ROW_RE.match(line)
                if not m:
                    continue
                cell_a, cell_b = _clean(m.group(1)), _clean(m.group(2))
                # Conversation tables: | Speaker: Kodava line | English gloss |
                # or | Kodava | English |
                if _is_skip(cell_a) and _is_skip(cell_b):
                    continue
                # Strip speaker label (e.g. "A:", "B:")
                kodava_raw = re.sub(r"^[A-Z]\.\s*", "", cell_a).strip()
                english_raw = cell_b
                if not kodava_raw or _is_skip(kodava_raw):
                    continue
                # Skip rows that are clearly English (no recognisable Kodava)
                if _looks_english(kodava_raw) and not _looks_english(english_raw):
                    kodava_raw, english_raw = english_raw, kodava_raw
                if not kodava_raw or len(kodava_raw) < 3:
                    continue
                entries.append(
                    CorpusEntry(
                        type="sentence",
                        kodava=kodava_raw,
                        devanagari="",
                        kannada="",
                        english=english_raw,
                        explanation="",
                        confidence="textbook",
                        source=path.name,
                        tags=tags,
                    )
                )

        flush_grammar()
        return entries


def _orient(cell_a: str, cell_b: str) -> tuple[str, str]:
    """Return (kodava, english) — heuristic based on content."""
    # If cell_a looks like an English word/phrase and cell_b does not → swap
    if _looks_english(cell_a) and not _looks_english(cell_b):
        return cell_b, cell_a
    return cell_a, cell_b


_ENGLISH_WORDS = frozenset(
    "the a an is are was were be been have has had do does did will would"
    " can could shall should may might must not no yes i you he she it we they"
    " what which who how when where why this that and or but for of to in on at"
    " with from by about into through after before between under over all".split()
)


def _looks_english(text: str) -> bool:
    """Rough heuristic: True if the text reads like English."""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return False
    english_count = sum(1 for w in words if w in _ENGLISH_WORDS)
    # If more than a third of words are common English words → probably English
    return english_count / len(words) > 0.3 or (
        len(words) >= 2 and english_count >= 1 and text[0].isupper()
    )
