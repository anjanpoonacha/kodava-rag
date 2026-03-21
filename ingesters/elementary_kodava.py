"""Ingester for elementary_kodava_FINAL.md — a 16-lesson Kodava textbook.

Extracts four entry types:
  vocabulary   — rows from VOCABULARY / IMPORTANT PHRASES tables
  grammar_rule — prose blocks AND conjugation tables under GRAMMATICAL EXPLANATION
                 sections, plus Review / verb-paradigm tables elsewhere
  sentence     — example sentences from grammar sections (2-col Kodava | English)
                 and dialogue lines from SAMPLE CONVERSATION tables
  phoneme      — rows from the Introduction alphabet table (romanization | example)
"""

from __future__ import annotations

import re
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

# ---------------------------------------------------------------------------
# Section-heading patterns
# ---------------------------------------------------------------------------

# Any lesson header
_LESSON_RE = re.compile(r"^#+ (?:LESSON|Lesson)\s+(\d+)\b", re.IGNORECASE)

# VOCABULARY / IMPORTANT PHRASES — matches both ATX (#) and bold (**) headings
_VOCAB_SECTION_RE = re.compile(
    r"^(?:#+.*\*{0,2}|\*{1,2})(VOCABULARY|Vocabulary|IMPORTANT PHRASES|Important Phrases)\*{0,2}:?",
    re.IGNORECASE,
)

# GRAMMATICAL EXPLANATION — matches ATX and bold headings
_GRAMMAR_SECTION_RE = re.compile(
    r"^(?:#+.*\*{0,2}|\*{1,2})(EXPLANATION|GRAMMATICAL EXPLANATION|Grammatical Explanation)\*{0,2}:?",
    re.IGNORECASE,
)

# SAMPLE CONVERSATION / Sample Dialogue
_CONV_SECTION_RE = re.compile(
    r"^(?:#+.*\*{0,2}|\*{1,2})(SAMPLE CONVERSATION|Sample Dialogue)\*{0,2}:?",
    re.IGNORECASE,
)

# Review sections (e.g. "# Review of Lessons 1-7:")
_REVIEW_SECTION_RE = re.compile(r"^#+\s+Review\b", re.IGNORECASE)

# Intro section (alphabet / phoneme table)
_INTRO_SECTION_RE = re.compile(r"^#+\s+Introduction\b", re.IGNORECASE)

# Sub-headings inside grammar sections that introduce conjugation tables
_CONJUGATION_RE = re.compile(
    r"(?:present|past|future|tense|negative|interrogative|progressive|conjugat"
    r"|pronoun|possessive|accusative|dative|locative|ablative|genitive"
    r"|paradigm|imperative)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Table row parsing
# ---------------------------------------------------------------------------

# Two-cell row (captures first two cells)
_ROW_RE = re.compile(r"^\|\s*([^\|]{1,120}?)\s*\|\s*([^\|]{1,120}?)\s*\|")

# Three-cell row (speaker | kodava | english) — used in sample dialogues
_ROW3_RE = re.compile(
    r"^\|\s*([^\|]{1,60}?)\s*\|\s*([^\|]{1,300}?)\s*\|\s*([^\|]{1,300}?)\s*\|"
)

# Separator row (|---|---|)
_SEP_RE = re.compile(r"^\|[\s\-|:]+\|$")

# Speaker labels used in sample dialogues — single letter + dot, or role words
_SPEAKER_RE = re.compile(
    r"^(?:[A-Z]\.|conductor|waiter|server|shopkeeper|host)\s*$", re.IGNORECASE
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
        "letter",
        "consonants",
        "vowels",
        "abbreviations for pronouns",
        "personal & object pronouns",
    }
)

# Pattern for table sub-header rows (e.g. "kayyuw'k, present tense negative: …")
# These are section labels inside a conjugation table, not actual content.
_TABLE_SUBHEADER_RE = re.compile(
    r"^[a-zA-Z'ê\-]+.*(?:present|past|future|tense|negative|interrogative|imperative)",
    re.IGNORECASE,
)

_MIN_LEN = 2


def _is_skip(cell: str) -> bool:
    cleaned = cell.lower().rstrip("-. *_")
    return cleaned in _SKIP_CELLS or len(cell) < _MIN_LEN


def _clean(s: str) -> str:
    # Strip bold/italic markers (** and *) and normalise whitespace.
    # Use a regex to remove all * and _ used for markdown emphasis rather than
    # .strip("*_") which only removes leading/trailing occurrences.
    s = re.sub(r"\*{1,2}|_{1,2}", "", s)
    return re.sub(r"\s+", " ", s.strip())


def _strip_footnotes(s: str) -> str:
    """Remove superscript footnote markers like ⁷ or inline note markers."""
    return re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+|<sup>[^<]*</sup>", "", s).strip()


# ---------------------------------------------------------------------------
# Content-type heuristics
# ---------------------------------------------------------------------------

_ENGLISH_WORDS = frozenset(
    "the a an is are was were be been have has had do does did will would"
    " can could shall should may might must not no yes i you he she it we they"
    " what which who how when where why this that and or but for of to in on at"
    " with from by about into through after before between under over all".split()
)


def _looks_english(text: str) -> bool:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return False
    english_count = sum(1 for w in words if w in _ENGLISH_WORDS)
    return english_count / len(words) > 0.3 or (
        len(words) >= 2 and english_count >= 1 and text[0].isupper()
    )


def _orient(cell_a: str, cell_b: str) -> tuple[str, str]:
    """Return (kodava, english). Swap if col_a looks like English and col_b does not."""
    if _looks_english(cell_a) and not _looks_english(cell_b):
        return cell_b, cell_a
    return cell_a, cell_b


def _looks_like_sentence(kodava: str) -> bool:
    """True if the kodava text looks like a sentence rather than a bare word."""
    stripped = kodava.strip().rstrip("?!.")
    return " " in stripped or stripped.endswith(("'k", "'l", "wii", "nê", "pii", "uNd"))


# ---------------------------------------------------------------------------
# Section constants
# ---------------------------------------------------------------------------


class _Section:
    NONE = "none"
    INTRO = "intro"
    VOCAB = "vocab"
    GRAMMAR = "grammar"
    CONV = "conv"
    REVIEW = "review"


# ---------------------------------------------------------------------------
# Ingester
# ---------------------------------------------------------------------------


@register
class ElementaryKodavaIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.name == "elementary_kodava_FINAL.md"

    def ingest(self, path: Path) -> list[CorpusEntry]:  # noqa: C901
        lines = path.read_text(encoding="utf-8").splitlines()
        entries: list[CorpusEntry] = []
        current_lesson = 0
        section = _Section.NONE
        grammar_buf: list[str] = []
        grammar_section_title = ""
        # Track heading text for grammar tables (conjugation context)
        last_grammar_subheading = ""

        def flush_grammar() -> None:
            if not grammar_buf:
                return
            text = " ".join(grammar_buf).strip()
            if len(text) < 20:
                return
            first = grammar_buf[0]
            m = re.search(r"\*{1,2}([a-zA-Z'êê\-]{2,30})\*{1,2}", first)
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

        def add_vocab(kodava: str, english: str, tags: list[str]) -> None:
            if not kodava or len(kodava) < _MIN_LEN:
                return
            entries.append(
                CorpusEntry(
                    type="vocabulary",
                    kodava=_strip_footnotes(kodava),
                    devanagari="",
                    kannada="",
                    english=_strip_footnotes(english),
                    explanation="",
                    confidence="textbook",
                    source=path.name,
                    tags=tags,
                )
            )

        def add_sentence(kodava: str, english: str, tags: list[str]) -> None:
            if not kodava or len(kodava) < 3:
                return
            entries.append(
                CorpusEntry(
                    type="sentence",
                    kodava=_strip_footnotes(kodava),
                    devanagari="",
                    kannada="",
                    english=_strip_footnotes(english),
                    explanation="",
                    confidence="textbook",
                    source=path.name,
                    tags=tags,
                )
            )

        def add_grammar_table_row(
            col_a: str, col_b: str, col_c: str, col_d: str, tags: list[str]
        ) -> None:
            """
            Emit a grammar_rule from a conjugation/paradigm table row.
            col_a / col_c = pronoun or subject label (English)
            col_b / col_d = Kodava conjugated form
            """
            context = last_grammar_subheading or grammar_section_title
            for subj, form in ((col_a, col_b), (col_c, col_d)):
                subj = _clean(subj)
                form = _clean(form)
                if not form or _is_skip(form) or _is_skip(subj):
                    continue
                if not form or len(form) < 2:
                    continue
                entries.append(
                    CorpusEntry(
                        type="grammar_rule",
                        kodava=_strip_footnotes(form),
                        devanagari="",
                        kannada="",
                        english=f"{subj} — {context}" if subj else context,
                        explanation=f"Conjugation table: {context}",
                        confidence="textbook",
                        source=path.name,
                        tags=tags,
                    )
                )

        def try_dialogue_row(stripped: str, tags: list[str]) -> bool:
            """
            Attempt to parse a 3-column | Speaker | Kodava | English | row.
            Returns True and emits a sentence entry if successful, else False.
            """
            m3 = _ROW3_RE.match(stripped)
            if not m3:
                return False
            speaker = _clean(m3.group(1))
            kodava_raw = _clean(m3.group(2))
            english_raw = _clean(m3.group(3))
            if not _SPEAKER_RE.match(speaker):
                return False
            # Strip stage directions (* ... *) from kodava
            kodava_clean = re.sub(r"\*[^*]*\*", "", kodava_raw).strip()
            kodava_clean = _strip_footnotes(kodava_clean)
            if not kodava_clean or len(kodava_clean) < 3:
                return False
            if _looks_english(kodava_clean) and not _looks_english(english_raw):
                kodava_clean, english_raw = english_raw, _strip_footnotes(kodava_clean)
            add_sentence(kodava_clean, _strip_footnotes(english_raw), tags)
            return True

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()

            # Skip page comments and standalone footnote lines
            if line.startswith("<!--") or re.match(r"^[⁰¹²³⁴⁵⁶⁷⁸⁹]+\s", stripped):
                continue

            tags = [f"lesson:{current_lesson}"] if current_lesson else []

            # ── Lesson heading ───────────────────────────────────────────────
            lm = _LESSON_RE.match(stripped)
            if lm:
                flush_grammar()
                current_lesson = int(lm.group(1))
                section = _Section.NONE
                continue

            # ── Named section headings ───────────────────────────────────────
            if _VOCAB_SECTION_RE.match(stripped):
                flush_grammar()
                section = _Section.VOCAB
                continue
            if _GRAMMAR_SECTION_RE.match(stripped):
                flush_grammar()
                section = _Section.GRAMMAR
                grammar_section_title = _clean(
                    re.sub(r"^#+\s*", "", stripped).strip("*_ ")
                )
                last_grammar_subheading = ""
                continue
            if _CONV_SECTION_RE.match(stripped):
                flush_grammar()
                section = _Section.CONV
                continue
            if _REVIEW_SECTION_RE.match(stripped):
                flush_grammar()
                section = _Section.REVIEW
                continue
            if _INTRO_SECTION_RE.match(stripped):
                flush_grammar()
                section = _Section.INTRO
                continue

            # Other #-headings reset to NONE (except inside grammar where sub-headings
            # label conjugation tables — track them for context)
            if re.match(r"^#{1,4}\s+", stripped) and not re.match(r"^#{5,}", stripped):
                if section == _Section.GRAMMAR:
                    flush_grammar()
                    last_grammar_subheading = _clean(
                        re.sub(r"^#+\s*", "", stripped).strip("*_ ")
                    )
                else:
                    flush_grammar()
                    section = _Section.NONE
                continue

            # ── Separator rows — always skip ─────────────────────────────────
            if _SEP_RE.match(stripped):
                continue

            # ── VOCAB section ─────────────────────────────────────────────────
            if section == _Section.VOCAB:
                if try_dialogue_row(stripped, tags):
                    continue
                m = _ROW_RE.match(stripped)
                if not m:
                    continue
                cell_a, cell_b = _clean(m.group(1)), _clean(m.group(2))
                if _is_skip(cell_a) or _is_skip(cell_b):
                    continue
                kodava, english = _orient(cell_a, cell_b)
                if not kodava:
                    continue
                add_vocab(kodava, english, tags)

            # ── GRAMMAR section ───────────────────────────────────────────────
            elif section == _Section.GRAMMAR:
                if not stripped:
                    continue

                if stripped.startswith("|"):
                    # Try 3-column speaker|kodava|english dialogue row first
                    if try_dialogue_row(stripped, tags):
                        continue

                    # Table row inside a grammar section
                    m = _ROW_RE.match(stripped)
                    if not m:
                        continue
                    ncols = stripped.count("|") - 1
                    cell_a = _clean(m.group(1))
                    cell_b = _clean(m.group(2))

                    if ncols >= 4:
                        # Conjugation / paradigm table:
                        # | pronoun | form | pronoun | form |
                        rest = stripped
                        cells = [_clean(c) for c in rest.strip("|").split("|")]
                        if len(cells) >= 4:
                            add_grammar_table_row(
                                cells[0],
                                cells[1],
                                cells[2] if len(cells) > 2 else "",
                                cells[3] if len(cells) > 3 else "",
                                tags,
                            )
                    elif ncols == 2:
                        # 2-column: either sentence example or vocabulary gloss.
                        # Skip rows where BOTH cells look like tense/paradigm labels
                        # (e.g. "kayyuw'k, present tense negative: … | present tense interrogative: …")
                        if _is_skip(cell_a) or _is_skip(cell_b):
                            continue
                        if _TABLE_SUBHEADER_RE.match(
                            cell_a
                        ) and _TABLE_SUBHEADER_RE.match(cell_b):
                            grammar_buf.append(f"{cell_a} / {cell_b}")
                            continue
                        kodava, english = _orient(cell_a, cell_b)
                        if not kodava or len(kodava) < 2:
                            continue
                        if _looks_like_sentence(kodava):
                            add_sentence(kodava, english, tags)
                        else:
                            add_vocab(kodava, english, tags)
                    # 3-column non-dialogue rows: accumulate as grammar prose
                    elif ncols == 3:
                        cells = [_clean(c) for c in stripped.strip("|").split("|")]
                        row_text = " | ".join(c for c in cells if c and not _is_skip(c))
                        if row_text:
                            grammar_buf.append(row_text)
                else:
                    # Prose line
                    if stripped.startswith("---") or stripped.startswith("___"):
                        continue
                    grammar_buf.append(stripped)

            # ── CONV section ──────────────────────────────────────────────────
            elif section == _Section.CONV:
                # 3-column speaker|kodava|english rows
                if try_dialogue_row(stripped, tags):
                    continue
                m = _ROW_RE.match(stripped)
                if not m:
                    continue
                cell_a, cell_b = _clean(m.group(1)), _clean(m.group(2))
                if _is_skip(cell_a) and _is_skip(cell_b):
                    continue
                # Strip speaker label (e.g. "A.", "B.")
                kodava_raw = re.sub(r"^[A-Z]\.\s*", "", cell_a).strip()
                english_raw = cell_b
                if not kodava_raw or _is_skip(kodava_raw):
                    continue
                if _looks_english(kodava_raw) and not _looks_english(english_raw):
                    kodava_raw, english_raw = english_raw, kodava_raw
                if not kodava_raw or len(kodava_raw) < 3:
                    continue
                add_sentence(kodava_raw, english_raw, tags)

            # ── REVIEW section ────────────────────────────────────────────────
            elif section == _Section.REVIEW:
                if try_dialogue_row(stripped, tags):
                    continue
                m = _ROW_RE.match(stripped)
                if not m:
                    continue
                ncols = stripped.count("|") - 1
                cell_a = _clean(m.group(1))
                cell_b = _clean(m.group(2))
                if _is_skip(cell_a) or _is_skip(cell_b):
                    continue

                if ncols >= 4:
                    # Multi-column review tables (question word paradigms etc.)
                    cells = [_clean(c) for c in stripped.strip("|").split("|")]
                    # Emit pairs: (label, kodava_form) for each pair of columns
                    for j in range(0, len(cells) - 1, 2):
                        eng = cells[j]
                        kov = cells[j + 1] if j + 1 < len(cells) else ""
                        if not kov or _is_skip(kov):
                            continue
                        if _looks_english(kov) and not _looks_english(eng):
                            eng, kov = kov, eng
                        if _looks_like_sentence(kov):
                            add_sentence(kov, eng, tags)
                        else:
                            add_vocab(kov, eng, tags)
                else:
                    kodava, english = _orient(cell_a, cell_b)
                    if not kodava or len(kodava) < 2:
                        continue
                    if _looks_like_sentence(kodava):
                        add_sentence(kodava, english, tags)
                    else:
                        add_vocab(kodava, english, tags)

            # ── INTRO section (alphabet table) ────────────────────────────────
            # The intro table has 4 columns: letter | approximant | kodava example | english
            # We extract the kodava example + english gloss as vocabulary entries.
            elif section == _Section.INTRO:
                if not stripped.startswith("|"):
                    continue
                cells = [_clean(c) for c in stripped.strip("|").split("|")]
                if len(cells) < 4:
                    continue
                # col 0 = romanization letter, col 2 = kodava example, col 3 = english
                letter = cells[0].strip("* _")
                example = cells[2]
                english = cells[3]
                if not example or not english or _is_skip(example) or _is_skip(english):
                    continue
                if _is_skip(letter):
                    continue
                # Emit as a vocabulary entry: kodava=example, english=english,
                # explanation=letter as the romanization key
                if len(example) >= 2 and len(english) >= 2:
                    entries.append(
                        CorpusEntry(
                            type="vocabulary",
                            kodava=_strip_footnotes(example),
                            devanagari="",
                            kannada="",
                            english=_strip_footnotes(english),
                            explanation=f"Romanization key: '{letter}'",
                            confidence="textbook",
                            source=path.name,
                            tags=tags,
                        )
                    )

        flush_grammar()
        return entries
