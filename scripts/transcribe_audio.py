#!/usr/bin/env python3
"""
Transcribe a Kodava audio file and extract a 4-column vocab table.

Writes two files to data/thakk/audio-vocab/<category>/<name>/:
  transcription.md  — timestamped dual-layer (Kannada script + romanized / meaning)
  vocab_table.md    — | English | Kodava Takk | Kannada Script | Explanation |

Usage:
    python scripts/transcribe_audio.py \\
        --audio  data/thakk/source/audio/mp3/session_04.mp3 \\
        --name   session_04 \\
        --category sessions

    # Skip transcription if transcription.md already exists:
    python scripts/transcribe_audio.py ... --skip-transcription

    # Skip vocab table (transcription only):
    python scripts/transcribe_audio.py ... --skip-vocab

Categories: sessions | quizzes | other
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL  # noqa: E402

CHAT_URL = f"{ANTHROPIC_BASE_URL}/v1/chat/completions"
THAKK_DIR = ROOT / "data" / "thakk" / "audio-vocab"

MIME_MAP = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}

TRANSCRIPTION_SYSTEM_PROMPT = """\
You are a Kodava takk language expert and transcriptionist.

Produce a timestamped dual-layer transcription of this audio.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use this format for every segment:

[MM:SS]
Kannada: <what was said — Kodava Takk written in Kannada script>
English: <what was said — Kodava Takk written in romanized English letters>
---
Kannada: <what it means — translation in Kannada language>
English: <what it means — translation in English>

For quiz audio, add Q1:/Q2: labels:

[MM:SS]
Q1:
Kannada: <question in Kannada script>
English: <question romanized>
---
Kannada: <meaning/answer in Kannada>
English: <meaning/answer in English>

Rules:
- Add a [MM:SS] timestamp at every natural segment boundary (phrase, word-group,
  question/answer pair). Aim for one segment per 10–30 seconds.
- ABOVE the --- line: transcription — exactly what was spoken, nothing added or
  removed. Kannada script for the script form. Romanized English for the Latin form.
- BELOW the --- line: translation — what it means.
- For pure English narration with no Kodava words, still add the timestamp and
  record the English narration below the --- line as English meaning.
- Timestamps must increase monotonically. Use [00:00] for the start.
- If a segment is inaudible, write [unclear] in both lines.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROMANIZATION CONVENTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Vowels:
  aa  = long A   (kaadu, maat)
  ii  = long I   (piir, niir)
  uu  = long U   (muund, kuutu)
  oa  = long O — ONE sound, write as "oa" never split into "o"+"a"  (koadu, thoar)
  ea  = long E — ONE sound, write as "ea" never split into "e"+"a"  (keaLu, meane)
  ê   = weak schwa

Consonants — CRITICAL, these are the OPPOSITE of standard romanization:
  d   = RETROFLEX D  (ಡ)  e.g. padikana, deva, duu
  dh  = DENTAL   d  (ದ)  e.g. dhumba, dhaar, mandira
  t   = RETROFLEX T  (ಟ)  e.g. tambuttu, otti, puttari
  th  = DENTAL   t  (ತ)  e.g. thakk, thimb, ninthii
  DD  = double retroflex D  (ಡ್ಡ)
  tt  = double retroflex T  (ಟ್ಟ)
  LL  = double retroflex L  (ಳ್ಳ)  e.g. uLL, kaLL, oLL

Case suffixes — always write with apostrophe:
  'k  = dative / infinitive  (mane'k, maaduw'k)
  'l  = locative             (mane'l, sante'l)
  'ra = genitive             (mane'ra, namma'ra)
  'nd = instrumental / with

EXCEPTION — demonstrative root "adh" (meaning "that / it"):
  adh, adhange, adhangalla, adhnge — do NOT respell or apply the dh→dental rule.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KANNADA SCRIPT CONVENTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Vowel mappings:
  a  → ಅ/ಾ    aa → ಆ/ಾ    i  → ಇ/ಿ    ii → ಈ/ೀ
  u  → ಉ/ು    uu → ಊ/ೂ    e  → ಎ/ೆ
  ea → ಏ/ೇ   (single character — NEVER ಏ+ಅ)
  o  → ಒ/ೊ
  oa → ಓ/ೋ   (single character — NEVER ಓ+ಅ)

Consonants:
  k→ಕ  g→ಗ  ch→ಚ  j→ಜ
  th→ತ (dental, NOT ಥ)    dh→ದ (dental, NOT ಧ)
  t→ಟ  (retroflex)         d→ಡ  (retroflex)
  n→ನ  N→ಣ  p→ಪ  b→ಬ  m→ಮ  y→ಯ  r→ರ  l→ಲ  v/w→ವ  s→ಸ  h→ಹ
  zh/ḷ/L→ಳ (retroflex lateral)

Geminates:  kk→ಕ್ಕ  tt→ಟ್ಟ  LL→ಳ್ಳ  nn→ನ್ನ  mm→ಮ್ಮ  etc.
Nasals:  nd→ಂಡ  ndh→ಂದ  nt→ಂಟ  nth→ಂತ  ng→ಂಗ  mb→ಂಬ

Case suffixes:  'k→ಕ್  'l→ಲ್  'ra→್ರ

EXCEPTION — adh→ಅಧ (NOT ಅದ)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KNOWN SPELLING CORRECTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Manotira/Manottira → Manavattira
  Bebbatt   → Pebbattu
  woyi      → uyi
  Kallala   → Kallaala
  kaLanji   → kalnji
  payisa    → payasa
  tambutt   → tambuttu
  Kroda desha → Kroodadesha
  joppekol  → joppe kole
  putthari  → puttari
  kavery    → kaveri

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETENESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Transcribe EVERY word — including intro, outro, credits, transitions.
If inaudible, write [unclear]. If overlap, write [overlap].\
"""

VOCAB_PROMPT_TEMPLATE = """\
Extract a structured vocabulary table from this Kodava takk transcription.

The transcription uses a timestamped dual-layer format:
  [MM:SS]
  Kannada: <Kodava Takk in Kannada script>   ← transcription (what was spoken)
  English: <Kodava Takk romanized>           ← transcription (same, Latin letters)
  ---
  Kannada: <meaning in Kannada language>     ← translation
  English: <meaning in English>              ← translation

OUTPUT FORMAT — a markdown file:

  # <Title> — Kodava Vocabulary
  > **Source:** <audio filename>
  > **Format:** <one-line description of the audio type>

  | English | Kodava Takk | Kannada Script | Explanation |
  |---------|-------------|----------------|-------------|
  | ...     | ...         | ...            | ...         |

  ## Topics Covered
  - <domain 1>
  - <domain 2>

EXTRACTION RULES:

Column sources:
  - English column      ← English meaning from the translation layer (below ---)
  - Kodava Takk column  ← romanized form from the English: transcription line (above ---)
  - Kannada Script column ← Kannada script from the Kannada: transcription line (above ---)
  - Explanation column  ← word-by-word gloss or cultural note (≤ 20 words)

Coverage rules:
  - Every [MM:SS] block MUST produce at least one row.
  - If a block has multiple words, one row per word.
  - For quiz Q&A blocks: answer is the vocabulary item; produce a row for it.
  - Repeated items still get rows — repetition in teaching signals importance.
  - Skip blocks that are pure English narration with no Kodava content.
  - Do NOT invent words not in the transcription.

Kannada Script column — apply ALL rules:
  oa→ಓ/ೋ (never split)  ea→ಏ/ೇ (never split)
  d→ಡ retroflex  dh→ದ dental  t→ಟ retroflex  th→ತ dental
  tt→ಟ್ಟ  LL→ಳ್ಳ  adh→ಅಧ (demonstrative exception)

TRANSCRIPT:
{transcription}\
"""


def _api_call(payload: dict, step_name: str) -> str:
    """POST to LiteLLM, return content string. Exits on any error."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        CHAT_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {ANTHROPIC_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"[ERROR] {step_name} HTTP {exc.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"[ERROR] {step_name} connection failed: {exc.reason}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print(f"[ERROR] {step_name} timed out after 600s", file=sys.stderr)
        sys.exit(1)

    usage = result.get("usage", {})
    finish = result["choices"][0].get("finish_reason", "?")
    content = result["choices"][0]["message"]["content"]

    print(
        f"  [{step_name}] finish={finish}"
        f"  prompt_tokens={usage.get('prompt_tokens')}"
        f"  completion_tokens={usage.get('completion_tokens')}"
    )

    if finish not in ("stop", "end_turn", "length"):
        print(f"  [WARN] unexpected finish_reason: {finish}", file=sys.stderr)

    # Guard: audio not received (tokens too low)
    if step_name == "transcribe" and (usage.get("prompt_tokens") or 0) < 500:
        print(
            "[ERROR] prompt_tokens < 500 — audio was not received by the model. "
            "Check MIME type and base64 encoding.",
            file=sys.stderr,
        )
        sys.exit(1)

    return content


def transcribe(audio_path: Path) -> str:
    mime = MIME_MAP.get(audio_path.suffix.lower(), "audio/mp3")
    print(
        f"  Encoding {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)..."
    )
    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")

    payload = {
        "model": "gemini-2.5-pro",
        "max_tokens": 65536,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": TRANSCRIPTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{audio_b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Transcribe this Kodava takk audio using the timestamped "
                            "dual-layer format. Produce [MM:SS] timestamps, Kannada "
                            "script + romanized English above the --- line, Kannada + "
                            "English translation below."
                        ),
                    },
                ],
            },
        ],
    }
    return _api_call(payload, "transcribe")


def extract_vocab(transcription: str) -> str:
    prompt = VOCAB_PROMPT_TEMPLATE.format(transcription=transcription)
    payload = {
        "model": "gemini-2.5-pro",
        "max_tokens": 32768,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }
    return _api_call(payload, "vocab")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, help="Path to audio file")
    parser.add_argument("--name", required=True, help="Directory slug, e.g. session_04")
    parser.add_argument(
        "--category",
        required=True,
        choices=["sessions", "quizzes", "other"],
        help="Video category",
    )
    parser.add_argument(
        "--skip-transcription",
        action="store_true",
        help="Reuse existing transcription.md (skip Step 1)",
    )
    parser.add_argument(
        "--skip-vocab",
        action="store_true",
        help="Save transcription only, skip vocab table (Step 2)",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio)
    if not audio_path.exists():
        print(f"[ERROR] Audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = THAKK_DIR / args.category / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    transcription_path = out_dir / "transcription.md"
    vocab_path = out_dir / "vocab_table.md"

    print(f"\n{'=' * 60}")
    print(
        f"  Audio    : {audio_path.name}  ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)"
    )
    print(f"  Output   : {out_dir.relative_to(ROOT)}")
    print(f"  Proxy    : {CHAT_URL}")
    print(f"{'=' * 60}\n")

    # ── Step 1: Transcription ──────────────────────────────────────────────
    if args.skip_transcription and transcription_path.exists():
        print("Step 1/2 — Reusing existing transcription.md")
        transcription = transcription_path.read_text(encoding="utf-8")
    else:
        print("Step 1/2 — Transcribing audio...")
        transcription = transcribe(audio_path)
        transcription_path.write_text(transcription, encoding="utf-8")
        seg_count = transcription.count("\n[")
        print(
            f"  Saved transcription.md  ({len(transcription)} chars, ~{seg_count} segments)"
        )

    if args.skip_vocab:
        print("\n  --skip-vocab set — done.")
        return

    # ── Step 2: Vocab table ────────────────────────────────────────────────
    print("\nStep 2/2 — Extracting vocab table...")
    vocab_table = extract_vocab(transcription)
    vocab_path.write_text(vocab_table.strip(), encoding="utf-8")
    row_count = vocab_table.count("\n|")
    print(f"  Saved vocab_table.md    ({len(vocab_table)} chars, ~{row_count} rows)")

    print(f"\n✓  {args.name} complete\n")


if __name__ == "__main__":
    main()
