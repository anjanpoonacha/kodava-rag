#!/usr/bin/env python3
"""
Validate Kannada script rendering in all vocab_table.md files.

Checks that every row where the Kodava Takk column ends in 'e' (short-e)
has a Kannada Script column that ends in the short-e matra ೆ (U+0CC6).

The Kannada inherent vowel is ಅ — a bare consonant with no matra implicitly
carries ಅ, not ಎ. When Kodava romanisation spells an explicit 'e', the
Kannada column must render it with the explicit ೆ matra.

Usage:
    python scripts/check_vocab_tables.py              # scan all tables
    python scripts/check_vocab_tables.py --fix        # auto-apply fixes (not yet implemented)

Exit code: 0 if clean, 1 if violations found.
"""

import pathlib
import re
import sys

THAKK_DIR = pathlib.Path(__file__).parent.parent / "data" / "thakk"
VOCAB_GLOB = "audio-vocab/**/*vocab_table*.md"

# Kannada short-e matra (U+0CC6) and virama/halant (U+0CCD)
SHORT_E_MATRA = "\u0cc6"
VIRAMA = "\u0ccd"

# Characters that legitimately end a Kannada word without a vowel matra:
#   - virama ್ (word ends in pure consonant, e.g. ಕ್)
#   - anusvara ಂ (nasalisation)
#   - visarga ಃ
#   - chandrabindu (not common in Kodava)
# Characters that legitimately end a Kannada script form without short-e:
#   - virama ್ (pure consonant)
#   - anusvara ಂ
#   - visarga ಃ
#   - long-e matra ೇ (ea → ಏ/ೇ — valid when Kodava form ends in '-iye', '-ye', or '-eye')
#   - other vowel matras: ಾ ಿ ೀ ು ೂ ೊ ೋ ೈ ೌ
LONG_E_MATRA = "\u0cc7"  # ೇ
ALL_EXEMPT_ENDINGS = {
    "\u0ccd",  # virama ್
    "\u0c82",  # anusvara ಂ
    "\u0c83",  # visarga ಃ
    LONG_E_MATRA,  # ೇ long-e — valid for -iye / -ye suffix forms
    "\u0cbe",  # ಾ aa-matra
    "\u0cbf",  # ಿ i-matra
    "\u0cc0",  # ೀ ii-matra
    "\u0cc1",  # ು u-matra
    "\u0cc2",  # ೂ uu-matra
    "\u0cca",  # ೊ o-matra
    "\u0ccb",  # ೋ oa-matra
    "\u0cc8",  # ೈ ai-matra
    "\u0ccc",  # ೌ au-matra
    "\u0cc3",  # ೃ ri-matra
}
# Keep old name for compat
MATRA_EXEMPT_ENDINGS = ALL_EXEMPT_ENDINGS


def _kodava_ends_in_plain_e(kodava: str) -> bool:
    """Return True if the Kodava Takk romanisation ends in plain 'e' (not 'ea', 'ee', 'ie')."""
    # Strip backtick code spans used in markdown tables
    text = kodava.strip().strip("`").strip()
    if not text:
        return False
    # Must end in 'e' but not be a long-E digraph (ea) or long-I (ee/ii)
    if not text.endswith("e"):
        return False
    # Exclude digraphs: ea, ee, ie, ue
    if len(text) >= 2 and text[-2] in ("e", "i", "u", "a"):
        return False
    return True


def _kannada_ends_in_short_e(kannada: str) -> bool:
    """Return True if the Kannada script ends in the short-e matra ೆ (possibly before punctuation)."""
    text = kannada.strip().strip("`").strip()
    # Strip trailing punctuation (?, !, .)
    text = text.rstrip("?!.")
    if not text:
        return False
    return text.endswith(SHORT_E_MATRA)


def _kannada_ends_exempt(kannada: str) -> bool:
    """Return True if the Kannada string ends in a legitimate non-short-e character."""
    text = kannada.strip().strip("`").strip()
    # Strip trailing punctuation
    text = text.rstrip("?!.")
    if not text:
        return False
    # Standalone Kannada vowel letters (not matras) are complete on their own —
    # ಇ, ಈ, ಉ, ಊ, ಎ, ಏ, ಒ, ಓ, ಅ, ಆ, ಐ, ಔ are full vowel characters needing no matra.
    standalone_vowels = {
        "\u0c85",  # ಅ
        "\u0c86",  # ಆ
        "\u0c87",  # ಇ
        "\u0c88",  # ಈ
        "\u0c89",  # ಉ
        "\u0c8a",  # ಊ
        "\u0c8e",  # ಎ
        "\u0c8f",  # ಏ
        "\u0c92",  # ಒ
        "\u0c93",  # ಓ
        "\u0c90",  # ಐ
        "\u0c94",  # ಔ
    }
    last = text[-1]
    return last in ALL_EXEMPT_ENDINGS or last in standalone_vowels


def parse_table_rows(path: pathlib.Path):
    """Yield (line_no, english, kodava, kannada) for every data row in a markdown table."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_table = False
    header_passed = False

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            header_passed = False
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # Remove empty cells from leading/trailing pipes
        cells = [c for c in cells if c != ""]

        if len(cells) < 3:
            continue

        # Detect header row (contains "English" or "Kodava")
        if re.search(r"(?i)\benglish\b|\bkodava\b", cells[0]):
            in_table = True
            header_passed = False
            continue

        # Detect separator row (---)
        if all(re.match(r"^[-:]+$", c) for c in cells):
            header_passed = True
            continue

        if not in_table:
            continue

        if len(cells) < 3:
            continue

        english = cells[0]
        kodava = cells[1]
        kannada = cells[2]

        yield line_no, english, kodava, kannada


def check_file(path: pathlib.Path) -> list[dict]:
    violations = []
    for line_no, english, kodava, kannada in parse_table_rows(path):
        if not _kodava_ends_in_plain_e(kodava):
            continue
        if _kannada_ends_in_short_e(kannada):
            continue
        if _kannada_ends_exempt(kannada):
            # Ends in virama/anusvara — valid (e.g. suffix-only forms)
            continue
        if not kannada.strip().strip("`").strip():
            # Empty Kannada column — separate concern, skip here
            continue

        # Derive expected Kannada: append ೆ to whatever is there
        # (This is a hint, not a guaranteed auto-fix — the last character
        # may need to change, e.g. if the inherent ಅ was written as a full ಅ)
        current = kannada.strip().strip("`").strip()
        expected = current + SHORT_E_MATRA

        violations.append(
            {
                "file": str(path.relative_to(THAKK_DIR.parent.parent)),
                "line": line_no,
                "english": english,
                "kodava": kodava,
                "kannada_is": current,
                "kannada_expected": expected,
            }
        )
    return violations


def main() -> int:
    tables = sorted(THAKK_DIR.glob(VOCAB_GLOB))
    if not tables:
        print(f"No vocab tables found under {THAKK_DIR / VOCAB_GLOB}", file=sys.stderr)
        return 1

    all_violations: list[dict] = []
    for path in tables:
        all_violations.extend(check_file(path))

    if not all_violations:
        print(f"All vocab tables OK — 0 violations ({len(tables)} files scanned)")
        return 0

    print(
        f"VIOLATIONS FOUND — {len(all_violations)} rows with missing short-e matra ೆ\n"
    )
    for v in all_violations:
        print(f"  {v['file']}:{v['line']}")
        print(f"    English : {v['english']}")
        print(f"    Kodava  : {v['kodava']}")
        print(
            f"    Kannada : {v['kannada_is']}  →  expected ending: {v['kannada_expected']}"
        )
        print()

    print(
        "Rule: A Kodava word ending in 'e' must produce the short-e matra ೆ (U+0CC6)\n"
        "      in Kannada script. The bare consonant form silently inserts ಅ instead.\n"
        "      Fix: append ೆ to the final consonant in the Kannada Script column."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
