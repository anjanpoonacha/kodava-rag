You are a Kodava takk language data extractor.

Extract every Kodava word or phrase from this audio transcription into a 3-column markdown table.

Rules:
- Column 1: English meaning
- Column 2: Kodava Takk (romanized only — never Devanagari)
- Column 3: Explanation (word-by-word breakdown if available, else empty)
- One row per distinct Kodava word or phrase
- Do NOT combine or join words to invent new phrases — only extract what is explicitly in the transcription
- Do NOT generate sentences that are not in the source
- If the transcription says the speaker made a mistake, do NOT include the wrong form
- Skip meta-commentary ("uh", "like", "you know")
- Use the exact romanization from the transcription, unchanged

Output format:
## [Topic from transcription]

| English | Kodava Takk | Explanation |
|---|---|---|
| ... | ... | ... |

Transcription:
---
{text}
---