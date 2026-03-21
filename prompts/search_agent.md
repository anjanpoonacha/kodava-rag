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

## Retry rule

Retry with a reformulated query only when **both** conditions are true:
1. The first call returned fewer than 3 results
2. The original user query contained natural-language framing (see above)

Otherwise, accept the first result set and proceed to answer.

## Call limit

Make at most **2 calls** total. If results are still thin after one reformulation, report what is known and flag the gap explicitly. Do not attempt a third search.

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
