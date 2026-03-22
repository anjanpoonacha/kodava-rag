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

---

## HOW TO RUN

Use the **Bash tool** to call `scripts/transcribe_audio.py`. This script
handles everything: encoding, API calls, error-checking, and file writing.
Do NOT write inline Python — call the script.

```bash
cd /Users/i548399/SAPDevelop/github.com/personal/kodava-rag

python scripts/transcribe_audio.py \
  --audio    <AUDIO_PATH> \
  --name     <NAME> \
  --category <CATEGORY>
```

- `AUDIO_PATH` — absolute or relative path to the MP3/WAV/M4A file
- `NAME`       — slug for the per-video directory (e.g. `quiz_01`, `session_04`)
- `CATEGORY`   — one of `sessions`, `quizzes`, `other`

### Flags

| Flag | When to use |
|------|-------------|
| `--skip-transcription` | `transcription.md` already exists — skip Step 1 and regenerate vocab table only |
| `--skip-vocab` | Save transcription only, skip vocab table |

### Example invocations

```bash
# Full pipeline (transcription + vocab table)
python scripts/transcribe_audio.py \
  --audio data/thakk/source/audio/mp3/session_04.mp3 \
  --name session_04 --category sessions

# Vocab table only (transcription already saved)
python scripts/transcribe_audio.py \
  --audio data/thakk/source/audio/mp3/quiz_01.mp3 \
  --name quiz_01 --category quizzes \
  --skip-transcription
```

---

## WHAT THE SCRIPT DOES

The script (`scripts/transcribe_audio.py`) runs two steps:

**Step 1 — Transcription** (Gemini 2.5 Pro, `max_tokens=65536`, `thinking=disabled`)

Sends the audio as a base64 `image_url` payload. The model produces a
timestamped dual-layer transcription in this format:

```
[MM:SS]
Kannada: <Kodava Takk in Kannada script>
English: <Kodava Takk romanized>
---
Kannada: <meaning in Kannada>
English: <meaning in English>
```

For quiz audio, segments use `Q1:` / `Q2:` labels above the `---` line.

**Step 2 — Vocab table** (Gemini 2.5 Pro, `max_tokens=32768`, `thinking=disabled`)

Sends the transcription text back and extracts a 4-column markdown table:

```
| English | Kodava Takk | Kannada Script | Explanation |
```

Every `[MM:SS]` block produces at least one row.

---

## ERROR HANDLING

The script exits with code 1 on any error:
- `prompt_tokens < 500` → audio not received (wrong MIME or encoding)
- HTTP 4xx/5xx → logged with body excerpt, immediate exit
- Timeout (600 s) → logged, immediate exit
- Missing audio file → logged, immediate exit

If the script exits non-zero, report the stderr output and do not retry
inline — diagnose the error first.

---

## AFTER THE SCRIPT COMPLETES

The script prints a summary. Report to the user:

- Audio file name and size
- `prompt_tokens` — confirms audio was received
- Segment count (`~N segments` from the script output)
- Vocab row count (`~N rows` from the script output)
- File paths saved
- Any `[unclear]` words (visible in the transcription file)

---

## STEP 5 — COMMIT TO THAKK (only when explicitly requested)

```bash
cd /Users/i548399/SAPDevelop/github.com/personal/kodava-rag/data/thakk
git add audio-vocab/<CATEGORY>/<NAME>/transcription.md \
        audio-vocab/<CATEGORY>/<NAME>/vocab_table.md
git commit -m "corpus: add <NAME> timestamped transcription and vocab table"
```

Do **not** push — the user pushes manually.
