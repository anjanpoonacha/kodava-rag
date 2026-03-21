Search the Kodava Takk corpus for vocabulary, grammar rules, sentences, or phoneme mappings.

## Collections

| Collection | Contains |
|---|---|
| `vocabulary` | Words, translations, Kannada and Devanagari script forms |
| `sentences` | Verified usage examples and full sentences |
| `grammar_rules` | Corrections, conjugation patterns, grammar rules |
| `phonemes` | Romanization → Kannada / Devanagari script mappings |

## Collection targeting

Target a specific collection when the question is clearly about one type:
- "what does X mean" / "how do you write X" → `vocabulary`
- "how do I say the sentence …" → `sentences`
- "is this grammatically correct" / "what is the past tense of …" → `grammar_rules`
- "how is the sound X written" / "what script character is …" → `phonemes`

Omit `collection` to search all four when the question spans multiple types.

## When to reformulate (and when not to)

**Reformulate only when the query contains natural-language framing** — phrases like:
- "how do I say …"
- "what is the word for …"
- "how do you say …"
- "tell me about …"
- "can I say …"
- "how do Kodava people …"

For these, extract the core keyword(s) and retry with a focused term.
Example: `"how do I say good morning"` → retry with `"morning greeting"`.

**Do NOT reformulate when the query is already a direct keyword or phrase** — a single noun, a Kodava word, a technical term, or a proper name. These are already the most precise possible BM25 tokens.

If a direct keyword search returns 0 hits, this is a corpus gap — not a query problem. Stop immediately and tell the user the word is not in the corpus. Do not broaden to synonyms or hypernyms.

Examples of words that must NOT be broadened:
- `"helicopter"` → do not try "aircraft", "vehicle", "flying machine"
- `"hospital"` → do not try "medical", "building", "clinic"
- `"internet"` → do not try "network", "technology"

Broadening produces unrelated context (e.g. `gaadi` = vehicle) that misleads the answer.

## "How to [verb]" queries — always two searches

When the user asks **"how to [verb]"** or any equivalent phrasing — "how to cook", "how to say", "how to greet", "the way to cook", "cooking method", "translate: how to cook" — the answer requires **two separate corpus lookups**, not one:

1. **The verb** — search for the action word first: `cook cooking` → surfaces `adige maaduva`, `adige maaduw'k`
2. **The manner word "how"** — search for the question/manner word separately: `how manner` → surfaces `ennane` (the Kodava word for "how")

The Kodava construction is: **`[verb infinitive] + ennane`** — e.g. `adige maaduva ennane` = "how to cook". Without the second search, `ennane` will never appear in your context and the answer will be incomplete.

**Always make both calls for any "how to [verb]" query**, regardless of how the question is phrased:
- "How to cook" → search `cook cooking`, then search `how manner`
- "Translate: how to cook" → search `cook cooking`, then search `how manner`
- "What is the Kodava for how to cook" → search `cook cooking`, then search `how manner`
- "Cooking method in Kodava" → search `cook cooking`, then search `how manner`
- "The way to cook in Kodava" → search `cook cooking`, then search `how manner`

## Retry rule

Retry with a reformulated query only when **both** conditions are true:
1. The first call returned fewer than 3 results
2. The original user query contained natural-language framing (see above)

Otherwise, accept the first result set and proceed to answer.

## Call limit

Make at most **3 calls** total (raised from 2 to accommodate the mandatory two-call pattern for "how to [verb]" queries). If results are still thin after searching, report what is known and flag the gap explicitly.

## Paragraph and extended-text requests

When the query asks for a paragraph, story, narrative, or multiple connected sentences, make a dedicated connective search call **before** attempting the answer:

```
search_kodava(query="conjunction connective and but because then or", collection="vocabulary")
```

This surfaces the available joining words:

| Kodava | Meaning |
|---|---|
| `pinynya` | and, also, after that, and then |
| `aachenge` | but, however |
| `adhnge` | because of this, for this reason |
| `ennang êNchenge` | because |
| `akka` | then, after that |
| `athava` | or |
| `injaang` | because (causal suffix) |
| `minynya` | before |
| `andhaka` | in that case |

If the connective search returns no results, do **not** attempt the paragraph. Instead, offer the relevant sentences as a verified sentence cluster and state explicitly which connector types are missing.
