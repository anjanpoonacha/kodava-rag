#!/usr/bin/env python3
"""Generate phoneme lookup tables in prompts from the single source of truth.

Source:  data/thakk/phoneme_table/kodava_devanagari_map.json
Targets: prompts/fill_kannada.md
         prompts/rag_assistant.md
         scripts/transcribe_audio.py

Each target file contains narrow generation markers that wrap ONLY the raw
lookup table rows (vowel standalone/matra, consonant list, geminate list,
nasal clusters). All surrounding hand-authored content is preserved unchanged:
CRITICAL rules, NEVER guards, positional 'e' rules, worked examples, LEXICAL
EXCEPTIONS, KNOWN SPELLING CORRECTIONS, confidence-flag rules, etc.

Marker syntax (named sections):
  <!-- PHONEME-RULES:VOWEL-TABLE:BEGIN -->  ...  <!-- PHONEME-RULES:VOWEL-TABLE:END -->
  <!-- PHONEME-RULES:CONSONANTS:BEGIN -->   ...  <!-- PHONEME-RULES:CONSONANTS:END -->
  <!-- PHONEME-RULES:GEMINATES:BEGIN -->    ...  <!-- PHONEME-RULES:GEMINATES:END -->
  <!-- PHONEME-RULES:NASALS:BEGIN -->       ...  <!-- PHONEME-RULES:NASALS:END -->

For .py files use # comments instead of HTML comments:
  # PHONEME-RULES:VOWEL-TABLE:BEGIN  ...  # PHONEME-RULES:VOWEL-TABLE:END

The marker names with suffix "(vocab)" or "(system)" are also matched — the
suffix is ignored, allowing multiple instances of the same section type in one
file (e.g. transcribe_audio.py has two prompt strings that both need geminates).

Usage:
    python scripts/generate_phoneme_rules.py [--dry-run]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PHONEME_MAP = ROOT / "data" / "thakk" / "phoneme_table" / "kodava_devanagari_map.json"
FILL_KANNADA = ROOT / "prompts" / "fill_kannada.md"
RAG_ASSISTANT = ROOT / "prompts" / "rag_assistant.md"
TRANSCRIBE = ROOT / "scripts" / "transcribe_audio.py"

# Kannada standalone vowel → (standalone_char, matra_char)
_KN_VOWELS: dict[str, tuple[str, str]] = {
    "a": ("ಅ", "ಾ"),
    "aa": ("ಆ", "ಾ"),
    "i": ("ಇ", "ಿ"),
    "ii": ("ಈ", "ೀ"),
    "u": ("ಉ", "ು"),
    "uu": ("ಊ", "ೂ"),
    "e": ("ಎ", "ೆ"),
    "ea": ("ಏ", "ೇ"),
    "o": ("ಒ", "ೊ"),
    "oa": ("ಓ", "ೋ"),
    "ai": ("ಐ", "ೈ"),
    "au": ("ಔ", "ೌ"),
    "ê": ("ಎ̈", "ೆ̈"),
    "ri": ("ಋ", "ೃ"),
}

# Kannada consonant character lookup
_KN_CONS: dict[str, str] = {
    "k": "ಕ",
    "g": "ಗ",
    "ch": "ಚ",
    "j": "ಜ",
    "t": "ಟ",
    "d": "ಡ",
    "th": "ತ",
    "dh": "ದ",
    "n": "ನ",
    "N": "ಣ",
    "l": "ಲ",
    "L": "ಳ",
    "m": "ಮ",
    "b": "ಬ",
    "p": "ಪ",
    "r": "ರ",
    "y": "ಯ",
    "w": "ವ",
    "v": "ವ",
    "s": "ಸ",
    "h": "ಹ",
    "ny": "ಞ",
    "ri": "ಋ",
    "kk": "ಕ್ಕ",
    "gg": "ಗ್ಗ",
    "chch": "ಚ್ಚ",
    "jj": "ಜ್ಜ",
    "tt": "ಟ್ಟ",
    "dd": "ಡ್ಡ",
    "DD": "ಡ್ಡ",
    "thth": "ತ್ತ",
    "dhdh": "ದ್ದ",
    "nn": "ನ್ನ",
    "NN": "ಣ್ಣ",
    "mm": "ಮ್ಮ",
    "ll": "ಲ್ಲ",
    "LL": "ಳ್ಳ",
    "rr": "ರ್ರ",
    "ss": "ಸ್ಸ",
    "pp": "ಪ್ಪ",
    "bb": "ಬ್ಬ",
    "nyny": "ಞ್ಞ",
}

_NASAL_CLUSTERS: dict[str, str] = {
    "nd": "ಂಡ",
    "ndh": "ಂದ",
    "nt": "ಂಟ",
    "nth": "ಂತ",
    "ng": "ಂಗ",
    "mb": "ಂಬ",
    "nj": "ಂಜ",
    "nny": "ಂಞ",
}


def _kn(p: dict) -> str:
    """Return Kannada character for a phoneme-map entry."""
    explicit = p.get("kannada", "")
    if explicit:
        return explicit
    k = p.get("kodava", "")
    if k in _KN_VOWELS:
        return _KN_VOWELS[k][0]
    return _KN_CONS.get(k, "")


# ─────────────────────────────────────────────────────────────────────────────
# Section generators — produce the body text for each named section
# ─────────────────────────────────────────────────────────────────────────────


def _gen_vowel_table_fill(data: dict) -> str:
    """Vowel table for fill_kannada.md (box-drawing table format).

    Canonical order matches the existing file. Excludes nasalised vowels
    (ãã, ĩĩ) which are too rare for the main table, and excludes ê/ri
    which are in the hand-authored schwa row below the separator.
    """
    # Ordered as they appear in the current prompt
    ordered = ["a", "aa", "i", "ii", "u", "uu", "e", "ea", "o", "oa", "ai", "au"]
    sounds = {
        "a": "u in country, bus",
        "aa": "o in honest, odd",
        "i": "i in itchy, wit",
        "ii": "ee in seek, teeth",
        "u": "oo in good, put",
        "uu": "oo in oops, pool",
        "e": "e in enter, egg  ← CRITICAL",
        "ea": "a in make, wait (long E)",
        "o": "a in water (Short O)",
        "oa": "o in loan (long O)",
        "ai": "i in kite, my",
        "au": "ou in out, cow",
    }
    lines = [
        "  Kodava  │ Standalone │ Matra (in CV syllable) │ Sound",
        "  ────────┼────────────┼───────────────────────┼─────────────────────────",
    ]
    for k in ordered:
        sa, ma = _KN_VOWELS.get(k, ("", ""))
        hint = sounds.get(k, "")
        lines.append(f"  {k:<8}│ {sa:<11}│ {ma:<6}│ {hint}")
    lines += [
        "  ────────┼────────────┼───────────────────────┼─────────────────────────",
        "  ê       │ (ಎ̈)        │ ೆ̈                     │ a in about (schwa — rare)",
    ]
    return "\n".join(lines)


def _gen_vowel_table_rag(data: dict) -> str:
    """Vowel table for rag_assistant.md — matches existing spacing style."""
    ordered = ["a", "aa", "i", "ii", "u", "uu", "ai", "au"]
    parts = []
    for k in ordered:
        sa, ma = _KN_VOWELS.get(k, ("", ""))
        # Pad key to 4 chars for alignment
        parts.append(f"{k:<4}→ {sa}/{ma}")
    row1 = "  " + "   ".join(parts[:4])
    row2 = "  " + "   ".join(parts[4:])
    return row1 + "\n" + row2


def _gen_vowel_table_py(data: dict, compact: bool = False) -> str:
    """Vowel table for transcribe_audio.py prompt strings."""
    core = [
        p
        for p in data["phonemes"]["vowels"]
        if p["kodava"] in ("a", "aa", "i", "ii", "u", "uu", "ai", "au")
    ]
    sep = "   " if compact else "    "
    parts = []
    for p in core:
        k = p["kodava"]
        sa, ma = _KN_VOWELS.get(k, ("", ""))
        parts.append(f"{k} →{sa}/{ma}")
    # Rows of 4
    rows = []
    for i in range(0, len(parts), 4):
        rows.append("  " + sep.join(parts[i : i + 4]))
    return "\n".join(rows)


_STD_CONS_ROWS = [
    ("k", "g", "ch", "j"),
    ("n", "p", "b", "m"),
    ("y", "r", "l", "v/w", "s", "h"),
]
# Exclude th/dh (in the hand-authored CRITICAL retroflex section) and ny/ri
_STD_CONS_EXCLUDED = {"th", "dh", "t", "d", "ny", "ri", "w"}


def _gen_consonants_fill(data: dict) -> str:
    kn = {"v/w": "ವ"}  # special alias
    rows_out = []
    for group in _STD_CONS_ROWS:
        parts = []
        for k in group:
            kn_char = kn.get(k) or _KN_CONS.get(k, "")
            parts.append(f"{k}→{kn_char}")
        rows_out.append("  " + "  ".join(parts))
    return "\n".join(rows_out)


def _gen_consonants_rag(data: dict) -> str:
    # Flat list matching current rag_assistant.md format,
    # excluding th/dh/t/d (in the hand-authored retroflex section) and ny/ri
    ordered = ["k", "g", "ch", "j", "n", "p", "b", "m", "y", "r", "l", "v/w", "s", "h"]
    kn = {"v/w": "ವ"}
    parts = [f"{k}→{kn.get(k) or _KN_CONS.get(k, '')}" for k in ordered]
    return "  Standard: " + "  ".join(parts)


def _gen_consonants_py(data: dict) -> str:
    return (
        "  k→ಕ  g→ಗ  ch→ಚ  j→ಜ\n"
        "  th→ತ (dental, NOT ಥ)    dh→ದ (dental, NOT ಧ)\n"
        "  t→ಟ  (retroflex)         d→ಡ  (retroflex)\n"
        "  n→ನ  N→ಣ  p→ಪ  b→ಬ  m→ಮ  y→ಯ  r→ರ  l→ಲ  v/w→ವ  s→ಸ  h→ಹ\n"
        "  zh/ḷ/L→ಳ (retroflex lateral)\n"
        "  ny→ಞ (palatal nasal — NEVER ನ+ಯ; geminate: nyny→ಞ್ಞ)\n"
        "  ri→ಋ/ೃ (vocalic r in Sanskrit-origin words)"
    )


def _gen_geminates(data: dict, compact: bool = False) -> str:
    gems = data["phonemes"]["geminate_consonants"]
    parts = []
    for p in gems:
        k = p["kodava"]
        kn = _kn(p) or p.get("devanagari", "")
        parts.append(f"{k}→{kn}")
    sep = "  "
    rows = []
    row_size = 7 if compact else 6
    for i in range(0, len(parts), row_size):
        rows.append("  " + sep.join(parts[i : i + row_size]))
    # Preserve the nn/NN distinction note inside the generated block
    rows.append("  NOTE: nn→ನ್ನ (dental n) ≠ NN→ಣ್ಣ (retroflex N)")
    rows.append("        enne→ಎಣ್ಣೆ (oil)  kaNNu→ಕಣ್ಣು (eye)  poNNa→ಪೊಣ್ಣ (girl)")
    return "\n".join(rows)


def _gen_geminates_py_vocab(data: dict) -> str:
    """Compact geminates for VOCAB_PROMPT_TEMPLATE — key ones with NN/nn distinction."""
    return (
        "  tt→ಟ್ಟ  LL→ಳ್ಳ  NN→ಣ್ಣ  nn→ನ್ನ  "
        "(NN=retroflex N ≠ nn=dental n: enne→ಎಣ್ಣೆ, kaNNu→ಕಣ್ಣು)"
    )


def _gen_nasals_fill(data: dict) -> str:
    labels = {
        "nd": "nasal + retroflex D",
        "ndh": "nasal + dental d",
        "nt": "nasal + retroflex T",
        "nth": "nasal + dental t",
        "ng": "nasal + g",
        "mb": "nasal + b",
        "nj": "nasal + j",
        "nny": "nasal + palatal nasal ಞ: pinja→ಪಿಂಞ, minja→ಮಿಂಞ, inyoo→ಇಂಞೂ",
    }
    lines = []
    for k, kn in _NASAL_CLUSTERS.items():
        label = labels.get(k, "")
        lines.append(f"  {k:<4} → {kn}   ({label})")
    return "\n".join(lines)


def _gen_nasals_compact(data: dict) -> str:
    parts = [f"{k}→{v}" for k, v in _NASAL_CLUSTERS.items()]
    return "  " + "  ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Marker replacement
# ─────────────────────────────────────────────────────────────────────────────


def _replace_section(
    content: str, name: str, new_body: str, py_style: bool
) -> tuple[str, int]:
    """Replace all instances of a named section. Returns (updated_content, count).

    Markers may carry an optional annotation suffix, e.g.:
      # PHONEME-RULES:VOWEL-TABLE:BEGIN (vocab)
      # PHONEME-RULES:VOWEL-TABLE:END (vocab)
    The suffix annotation is preserved verbatim on replacement.
    """
    if py_style:
        # Python comment markers — no closing token
        # BEGIN and END may have optional annotation: "# PHONEME-RULES:X:BEGIN (vocab)"
        pattern = re.compile(
            r"(# PHONEME-RULES:"
            + re.escape(name)
            + r":BEGIN(?:[^\n]*))\n"
            + r".*?\n"
            + r"(# PHONEME-RULES:"
            + re.escape(name)
            + r":END(?:[^\n]*))(?=\n|$)",
            re.DOTALL,
        )

        def _repl(m: re.Match) -> str:
            return f"{m.group(1)}\n{new_body}\n{m.group(2)}"
    else:
        # HTML comment markers — format: <!-- PHONEME-RULES:X:BEGIN -->
        # Optional annotation appears BEFORE the closing -->
        pattern = re.compile(
            r"(<!-- PHONEME-RULES:"
            + re.escape(name)
            + r":BEGIN(?:[^-]|-(?!->))*-->)\n"
            + r".*?\n"
            + r"(<!-- PHONEME-RULES:"
            + re.escape(name)
            + r":END(?:[^-]|-(?!->))*-->)",
            re.DOTALL,
        )

        def _repl(m: re.Match) -> str:  # noqa: F811
            return f"{m.group(1)}\n{new_body}\n{m.group(2)}"

    new_content, count = pattern.subn(_repl, content)
    return new_content, count


def update_file(path: Path, sections: dict[str, str], dry_run: bool) -> None:
    """Apply all section replacements to a file."""
    py_style = path.suffix == ".py"
    original = path.read_text(encoding="utf-8")
    current = original
    total_replacements = 0

    for name, body in sections.items():
        current, count = _replace_section(current, name, body, py_style)
        total_replacements += count

    if total_replacements == 0:
        print(f"  SKIP {path.relative_to(ROOT)}: no markers matched")
        return

    if current == original:
        print(f"  UNCHANGED {path.relative_to(ROOT)}")
        return

    if dry_run:
        import difflib

        diff = list(
            difflib.unified_diff(
                original.splitlines(),
                current.splitlines(),
                fromfile=str(path.relative_to(ROOT)),
                tofile=str(path.relative_to(ROOT)),
                lineterm="",
            )
        )
        print(
            f"  DRY-RUN {path.relative_to(ROOT)}: {total_replacements} section(s) updated"
        )
        for line in diff[:40]:
            print("    " + line)
        if len(diff) > 40:
            print(f"    ... ({len(diff) - 40} more lines)")
    else:
        path.write_text(current, encoding="utf-8")
        print(f"  updated {path.relative_to(ROOT)} ({total_replacements} section(s))")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    data = json.loads(PHONEME_MAP.read_text(encoding="utf-8"))

    print("Generating from:", PHONEME_MAP.relative_to(ROOT))
    print()

    # fill_kannada.md — table format with box-drawing characters
    update_file(
        FILL_KANNADA,
        {
            "VOWEL-TABLE": _gen_vowel_table_fill(data),
            "CONSONANTS": _gen_consonants_fill(data),
            "GEMINATES": _gen_geminates(data),
            "NASALS": _gen_nasals_fill(data),
        },
        dry_run,
    )

    # rag_assistant.md — compact inline format
    update_file(
        RAG_ASSISTANT,
        {
            "VOWEL-TABLE": _gen_vowel_table_rag(data),
            "CONSONANTS": _gen_consonants_rag(data),
            "NASALS": _gen_nasals_compact(data),
        },
        dry_run,
    )

    # transcribe_audio.py — two prompt strings, indented
    # TRANSCRIPTION_SYSTEM_PROMPT uses VOWEL-TABLE, CONSONANTS, GEMINATES, NASALS
    # VOCAB_PROMPT_TEMPLATE uses VOWEL-TABLE (vocab) and GEMINATES (vocab)
    update_file(
        TRANSCRIBE,
        {
            "VOWEL-TABLE": _gen_vowel_table_py(data),
            "CONSONANTS": _gen_consonants_py(data),
            "GEMINATES": _gen_geminates(data, compact=True),
            "NASALS": _gen_nasals_compact(data),
            # vocab section uses same marker name with suffix — matched by the same name
        },
        dry_run,
    )

    if not dry_run:
        print()
        print("Done. Review and commit:")
        print("  git diff prompts/ scripts/transcribe_audio.py")


if __name__ == "__main__":
    main()
