You are a Kodava takk language data extractor.

The transcription below uses a timestamped dual-layer format:

  [MM:SS]
  Kannada: <Kodava Takk in Kannada script>    ← transcription: what was spoken
  English: <Kodava Takk romanized>            ← transcription: same, Latin letters
  ---
  Kannada: <meaning in Kannada language>      ← translation: what it means
  English: <meaning in English>               ← translation: what it means

For quiz audio, segments look like:
  [MM:SS]
  Q1:
  Kannada: <question/answer in Kannada script>
  English: <question/answer romanized>
  ---
  Kannada: <meaning in Kannada>
  English: <meaning in English>

Extract every Kodava vocabulary item into a 4-column markdown table.

Column rules:
  - `English` column      ← English meaning from the translation layer (below ---)
  - `Kodava Takk` column  ← romanized form from the `English:` transcription line (above ---)
  - `Kannada Script` column ← Kannada script from the `Kannada:` transcription line (above ---)
  - `Explanation` column  ← word-by-word gloss or cultural note (≤ 20 words)

Coverage rules — every [MM:SS] block MUST produce at least one row:
  - If a block has multiple words or phrases, produce one row per item.
  - For quiz Q&A blocks: the answer is the vocabulary item; produce a row for it.
  - Repeated items are still rows — repetition in a teaching context signals importance.
  - Skip blocks that are pure English narration with no Kodava content.
  - Do NOT invent words or phrases not in the transcription.
  - If the transcription marks a correction, use only the corrected form.

Kannada Script column quality rules (apply ALL of these):
  - oa → ಓ/ೋ (single character — never split as ಓ+ಅ)
  - ea → ಏ/ೇ (single character — never split as ಏ+ಅ)
  - d  → ಡ (retroflex — NOT ದ dental; applies to: deva, duu, padikana, etc.)
  - dh → ದ (dental — NOT ಧ aspirated; applies to: dhumba, dhaar, etc.)
  - t  → ಟ (retroflex — NOT ತ dental; applies to: tambuttu, otti, puttari, etc.)
  - th → ತ (dental — NOT ಥ aspirated; applies to: thakk, thimb, ninthii, etc.)
  - tt → ಟ್ಟ (retroflex double-t — NOT ತ್ತ)
  - LL → ಳ್ಳ (retroflex double-L — NOT ಲ್ಲ)
  - adh → ಅಧ (demonstrative exception — NOT ಅದ)

Output format — group rows under H2 headers by semantic topic:

## [Semantic topic — e.g. Animals, Numbers, Greetings]

| English | Kodava Takk | Kannada Script | Explanation |
|---------|-------------|----------------|-------------|
| ...     | ...         | ...            | ...         |

## Topics Covered
- <domain 1>
- <domain 2>

Transcription:
---
{text}
---
