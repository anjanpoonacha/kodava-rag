---
description: >
  Transcribes any Kodava takk audio file (MP3/WAV/M4A) via Gemini 2.5 Pro,
  produces a timestamped dual-language transcription (Kannada script + romanized
  English, plus Kannada/English translation per segment), and saves a
  4-column vocab table (English | Kodava Takk | Kannada Script | Explanation)
  into data/thakk/audio-vocab/<category>/<name>/. Auto-invoke when the user
  asks to transcribe, ingest, or process a Kodava audio file in this project —
  quiz, lesson, conversation, story, song, or any other format.
mode: subagent
temperature: 0.1
permission:
  "*": allow
  task: deny
---

# Kodava Audio Transcriber & Vocab Table Builder

Transcribes any Kodava takk audio file and produces:
1. A **timestamped dual-language `transcription.md`** — what was said (Kannada
   script + romanized) and what it means (Kannada + English), per segment
2. A **4-column `vocab_table.md`** derived from the transcription

Saved into `data/thakk/audio-vocab/<category>/<name>/`.

Works for any audio type: **quiz, teaching lesson, conversation, story, song,
vocabulary drill, grammar explanation, field recording**, etc.

---

## CONFIGURATION

```python
import sys
sys.path.insert(0, '/Users/i548399/SAPDevelop/github.com/personal/kodava-rag')
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL
GEMINI_MODEL = "gemini-2.5-pro"
CHAT_URL     = f"{ANTHROPIC_BASE_URL}/v1/chat/completions"
```

---

## STEP 0 — DETERMINE OUTPUT DIRECTORY

The user will provide:
- `AUDIO_PATH` — path to the MP3/WAV/M4A file
- `NAME` — slug for the per-video directory (e.g. `quiz_01`, `session_04`)
- `CATEGORY` — one of `sessions`, `quizzes`, `other`

Output directory: `data/thakk/audio-vocab/<CATEGORY>/<NAME>/`

Create the directory if it does not exist:
```python
from pathlib import Path
THAKK_DIR = Path("/Users/i548399/SAPDevelop/github.com/personal/kodava-rag/data/thakk/audio-vocab")
out_dir = THAKK_DIR / CATEGORY / NAME
out_dir.mkdir(parents=True, exist_ok=True)
```

---

## STEP 1 — TRANSCRIBE

Send the audio to Gemini 2.5 Pro via the LiteLLM proxy.

**Audio format rule:** use `image_url` with a `data:<mime>;base64,…` URI.
Never use `document`, `inline_data`, or `input_audio` — those are rejected by the proxy.

Supported MIME types: `audio/mp3`, `audio/wav`, `audio/mp4` (m4a), `audio/ogg`, `audio/flac`.

```python
import sys, base64, json, urllib.request
sys.path.insert(0, '/Users/i548399/SAPDevelop/github.com/personal/kodava-rag')
from pathlib import Path
from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL

AUDIO_PATH = Path("REPLACE_WITH_AUDIO_PATH")
MIME_MAP   = {'.mp3':'audio/mp3','.wav':'audio/wav','.m4a':'audio/mp4',
              '.ogg':'audio/ogg','.flac':'audio/flac'}
mime_type  = MIME_MAP.get(AUDIO_PATH.suffix.lower(), 'audio/mp3')
audio_b64  = base64.b64encode(AUDIO_PATH.read_bytes()).decode('ascii')

SYSTEM_PROMPT = """You are a Kodava takk language expert and transcriptionist.

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
- BELOW the --- line: translation — what it means. Kannada translation in Kannada.
  English translation in English.
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
  ê   = weak schwa  (mane'k → manê'k when unstressed)

Consonants — CRITICAL, these are the OPPOSITE of standard romanization:
  d   = RETROFLEX D  (ಡ)  e.g. padikana, deva, duu
  dh  = DENTAL   d  (ದ)  e.g. dhumba, dhaar, mandira
  t   = RETROFLEX T  (ಟ)  e.g. tambuttu, otti, puttari
  th  = DENTAL   t  (ತ)  e.g. thakk, thimb, ninthii
  DD  = double retroflex D  (ಡ್ಡ)
  tt  = double retroflex T  (ಟ್ಟ)
  LL  = double retroflex L  (ಳ್ಳ)  e.g. uLL, kaLL, oLL
  ng  = velar nasal before vowels; anusvara ಂ before consonants

Case suffixes — always write with apostrophe:
  'k  = dative / infinitive  (mane'k, maaduw'k)
  'l  = locative             (mane'l, sante'l)
  'ra = genitive             (mane'ra, namma'ra)
  'nd = instrumental / with

EXCEPTION — the demonstrative root "adh" (meaning "that / it") is a fixed
lexical form. Write it and all its compounds as:
  adh, adhange, adhangalla, adhnge
Do NOT respell as "ad" or apply the dh→dental rule to this root.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KANNADA SCRIPT CONVENTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Vowel mappings:
  a  → ಅ (word-initial) / ಾ (post-consonant)
  aa → ಆ / ಾ
  i  → ಇ / ಿ
  ii → ಈ / ೀ
  u  → ಉ / ು
  uu → ಊ / ೂ
  e  → ಎ / ೆ
  ea → ಏ / ೇ   ← single character, NEVER ಏ+ಅ
  o  → ಒ / ೊ
  oa → ಓ / ೋ   ← single character, NEVER ಓ+ಅ

Consonant mappings — CRITICAL:
  k  → ಕ    g  → ಗ    ng → ಂಗ / ಂ
  ch → ಚ    j  → ಜ
  th → ತ    ← dental t   (NOT ಥ aspirated)
  dh → ದ    ← dental d   (NOT ಧ aspirated)
  t  → ಟ    ← retroflex  (NOT ತ dental)
  d  → ಡ    ← retroflex  (NOT ದ dental)
  n  → ನ    N  → ಣ (retroflex n)
  p  → ಪ    b  → ಬ    m  → ಮ
  y  → ಯ    r  → ರ    l  → ಲ    v/w → ವ
  s  → ಸ    h  → ಹ
  zh / ḷ / L → ಳ   (retroflex lateral approximant)

Geminate consonants (double = halant + repeat):
  kk  → ಕ್ಕ    gg  → ಗ್ಗ    chch → ಚ್ಚ    jj  → ಜ್ಜ
  thth → ತ್ತ   dhdh → ದ್ದ
  tt  → ಟ್ಟ    DD  → ಡ್ಡ
  nn  → ನ್ನ    ll  → ಲ್ಲ    LL  → ಳ್ಳ
  mm  → ಮ್ಮ    pp  → ಪ್ಪ    bb  → ಬ್ಬ

Nasal + consonant clusters:
  nd  → ಂಡ   ndh → ಂದ   nt  → ಂಟ   nth → ಂತ
  ng  → ಂಗ   mb  → ಂಬ   nch → ಂಚ

Case suffix rendering:
  'k  → ಕ್  (halant k — dative)
  'l  → ಲ್  (halant l — locative)
  'ra → ್ರ  (genitive — virama + ra joins to prior consonant)

EXCEPTION — demonstrative root "adh":
  adh         → ಅಧ    (NOT ಅದ — fixed lexical form)
  adhange     → ಅಧಂಗೆ
  adhangalla  → ಅಧಂಗಲ್ಲ
  adhnge      → ಅಧ್ಂಗೆ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KNOWN SPELLING CORRECTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Apply these wherever the audio sounds like the left column:

  Manotira     → Manavattira    (okka near Talakaveri)
  Manottira    → Manavattira
  Bebbatt      → Pebbattu       (part of Kaira ornament)
  woyi         → uyi            (part of Kaira ornament)
  Kallala      → Kallaala       (deity name)
  kaLanji      → kalnji         (Puttari food item)
  payisa       → payasa         (rice pudding)
  tambutt      → tambuttu       (Puttari food item)
  Kroda desha  → Kroodadesha    (historical name for Kodagu)
  joppekol     → joppe kole     (folk dance instrument)
  putthari     → puttari        (harvest festival — single t)
  kavery       → kaveri         (river name)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETENESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Transcribe EVERY word — including intro, outro, credits, transitions.
- If a word is genuinely inaudible, write [unclear].
- If two speakers overlap, transcribe both with a note: [overlap].
- Preserve any English, Kannada, or Hindi words exactly as spoken.
"""

payload = {
    "model": "gemini-2.5-pro",
    "max_tokens": 8192,
    "temperature": 0.1,
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{audio_b64}"}
                },
                {
                    "type": "text",
                    "text": "Transcribe this Kodava takk audio using the timestamped dual-layer format above. Produce [MM:SS] timestamps, Kannada script + romanized English above the --- line, Kannada + English translation below."
                }
            ]
        }
    ]
}

data = json.dumps(payload).encode()
req  = urllib.request.Request(
    f"{ANTHROPIC_BASE_URL}/v1/chat/completions",
    data=data,
    headers={"Authorization": f"Bearer {ANTHROPIC_API_KEY}", "Content-Type": "application/json"},
    method="POST"
)

with urllib.request.urlopen(req, timeout=300) as resp:
    result = json.loads(resp.read())

usage         = result.get("usage", {})
transcription = result["choices"][0]["message"]["content"]

print(f"prompt_tokens:     {usage.get('prompt_tokens')}")
print(f"completion_tokens: {usage.get('completion_tokens')}")
print("---BEGIN_TRANSCRIPTION---")
print(transcription)
print("---END_TRANSCRIPTION---")
```

**Token check:** `prompt_tokens` must be > 500. Values < 50 mean the audio was
not received — do not proceed, report the error.

---

## STEP 2 — BUILD VOCAB TABLE

Send the transcription (text only) back to Gemini to extract a 4-column table.

```python
VOCAB_PROMPT = f"""Extract a structured vocabulary table from this Kodava takk transcription.

The transcription uses a timestamped dual-layer format:
  [MM:SS]
  Kannada: <Kodava Takk in Kannada script>   ← transcription
  English: <Kodava Takk romanized>           ← transcription
  ---
  Kannada: <meaning in Kannada>              ← translation
  English: <meaning in English>              ← translation

OUTPUT FORMAT — a markdown file:

  # <Title> — Kodava Vocabulary
  > **Source:** <YouTube URL or file path>
  > **Format:** <one-line description of the audio type>

  | English | Kodava Takk | Kannada Script | Explanation |
  |---------|-------------|----------------|-------------|
  | ...     | ...         | ...            | ...         |

  ## Topics Covered
  - <semantic domain 1>
  - <semantic domain 2>

EXTRACTION RULES:

Column sources:
  - `English` column      ← English meaning from the translation layer (below ---)
  - `Kodava Takk` column  ← romanized form from the `English:` transcription line (above ---)
  - `Kannada Script` column ← Kannada script from the `Kannada:` transcription line (above ---)
  - `Explanation` column  ← word-by-word gloss or cultural context (≤ 20 words)

Coverage rules — every [MM:SS] block must produce at least one row:
  - If a block has multiple words, produce one row per word.
  - For quiz blocks (Q1/Q2): the answer is the vocabulary item; produce a row for it.
  - Do NOT skip a block because it seems obvious or repeated — repetition signals importance.
  - If a block is pure English narration (no Kodava words), skip it.

Kannada Script column — apply ALL rules from the transcription (oa→ಓ, ea→ಏ,
d→ಡ retroflex, dh→ದ dental, t→ಟ retroflex, th→ತ dental, adh→ಅಧ exception).
Scan and fix any violations before writing the table.

TRANSCRIPT:
{transcription}
"""

payload2 = {{
    "model": "gemini-2.5-pro",
    "max_tokens": 4096,
    "temperature": 0.1,
    "messages": [{{"role": "user", "content": VOCAB_PROMPT}}]
}}

data2 = json.dumps(payload2).encode()
req2  = urllib.request.Request(
    f"{ANTHROPIC_BASE_URL}/v1/chat/completions",
    data=data2,
    headers={{"Authorization": f"Bearer {ANTHROPIC_API_KEY}", "Content-Type": "application/json"}},
    method="POST"
)

with urllib.request.urlopen(req2, timeout=120) as resp2:
    result2 = json.loads(resp2.read())

vocab_table = result2["choices"][0]["message"]["content"]
print("---BEGIN_VOCAB---")
print(vocab_table)
print("---END_VOCAB---")
```

---

## STEP 3 — KANNADA SCRIPT QA

Before saving, scan the Kannada Script column for these violations and fix any found:

| Rule | Wrong | Correct |
|------|-------|---------|
| oa → ಓ (single char) | ಓಅ (two chars) | ಓ |
| ea → ಏ (single char) | ಏಅ (two chars) | ಏ |
| d → ಡ (retroflex) | ದ for words like deva, duu | ಡ |
| dh → ದ (dental) | ಧ for words like dhumba, dhaar | ದ |
| t → ಟ (retroflex) | ತ for words like tambuttu, otti | ಟ |
| th → ತ (dental) | ಥ for words like thakk, thimb | ತ |
| tt → ಟ್ಟ | ತ್ತ for retroflex double-t | ಟ್ಟ |
| LL → ಳ್ಳ | ಲ್ಲ for retroflex double-L | ಳ್ಳ |
| adh → ಅಧ | ಅದ (wrong — demonstrative exception) | ಅಧ |

---

## STEP 4 — SAVE FILES

```python
from pathlib import Path

THAKK_DIR = Path("/Users/i548399/SAPDevelop/github.com/personal/kodava-rag/data/thakk/audio-vocab")
# CATEGORY = "sessions" | "quizzes" | "other"
# NAME     = slug, e.g. "session_04", "quiz_01", "kaveri_sankramana"
out_dir = THAKK_DIR / CATEGORY / NAME
out_dir.mkdir(parents=True, exist_ok=True)

transcription_path = out_dir / "transcription.md"
vocab_path         = out_dir / "vocab_table.md"

transcription_path.write_text(transcription, encoding="utf-8")
vocab_path.write_text(vocab_table.strip(), encoding="utf-8")

print(f"Saved transcription: {transcription_path}")
print(f"Saved vocab table:   {vocab_path}")
```

---

## STEP 5 — COMMIT TO THAKK

```bash
cd /Users/i548399/SAPDevelop/github.com/personal/kodava-rag/data/thakk
git add audio-vocab/<CATEGORY>/<NAME>/transcription.md audio-vocab/<CATEGORY>/<NAME>/vocab_table.md
git commit -m "corpus: add <NAME> timestamped transcription and vocab table"
```

Do **not** push — the user pushes manually.

---

## ERROR HANDLING

| Error | Cause | Fix |
|-------|-------|-----|
| `prompt_tokens` < 50 | Audio not received | Use `image_url` data URI, not `document` or `inline_data` |
| HTTP 400 `Input should be 'application/pdf'` | Wrong block type | Use `image_url`, not `document` |
| HTTP 400 `Input tag 'media' found` | Wrong block type | Use `image_url` |
| HTTP 401 | Missing auth header | Use `Authorization: Bearer <key>` |
| Timeout | Large file | Increase timeout to 300s; 6MB ≈ 180s |

---

## FINAL REPORT

After completing all steps, report:

- Audio file name, size, and duration
- Audio type detected (quiz / lesson / conversation / story / song / other)
- `prompt_tokens` — confirms audio was received
- Transcription length (characters) and segment count (number of [MM:SS] blocks)
- Vocab table row count
- Files saved (both paths)
- Commit SHA
- Any [unclear] words or spelling corrections applied
