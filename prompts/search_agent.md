Search the Kodava Takk corpus for vocabulary, grammar rules, sentences, or phoneme mappings.

## Collections

| Collection | Contains |
|---|---|
| `vocabulary` | Words, translations, Kannada and Devanagari script forms |
| `sentences_lesson` | Lesson sentences from the elementary textbook |
| `sentences_narrative` | Narrative sentences from native speaker audio (incl. festival transcriptions) |
| `grammar_rules` | Corrections, conjugation patterns, grammar rules |
| `phonemes` | Romanization → Kannada / Devanagari script mappings |

## Collection targeting

Target a specific collection when the question is clearly about one type:
- "what does X mean" / "how do you write X" → `vocabulary`
- "how do I say the sentence …" / cultural topic queries ("how do Kodavas celebrate X", "tell me about festival Y") → `sentences_narrative`
- textbook pattern examples / lesson phrases → `sentences_lesson`
- "is this grammatically correct" / "what is the past tense of …" / "what does suffix X mean" → `grammar_rules`
- "how is the sound X written" / "what script character is …" → `phonemes`

Omit `collection` to search all when the question spans multiple types.

**Script rendering queries** — when the user asks for Devanagari, Kannada script, or any written form of a word ("write X in Kannada", "give me the script for X", "what is X in Devanagari"):
1. Search `vocabulary` first — the entry may already contain filled script fields
2. Always also search `phonemes` — needed when script fields are empty
Both calls are required for any script request. The `phonemes` call is never optional.

## When to reformulate (and when not to)

**Reformulate only when the query contains natural-language framing** — phrases like:
- "how do I say …"
- "what is the word for …"
- "how do you say …"
- "tell me about …"
- "can I say …"
- "how do Kodava people …"

For these, extract the core keyword(s) and search with a focused term.
Example: `"how do I say good morning"` → search `"morning greeting"`.

**Do NOT reformulate when the query is already a direct keyword or phrase** — a single noun, a Kodava word, a technical term, or a proper name. These are already the most precise possible BM25 tokens.

Examples of words that must NOT be broadened:
- `"helicopter"` → do not try "aircraft", "vehicle", "flying machine"
- `"hospital"` → do not try "medical", "building", "clinic"
- `"ennane"` (Kodava word for "how") → do not expand to "how manner" — search it directly
- `"what does ennane mean"` → search `ennane` in vocabulary directly; do NOT reformulate

Broadening produces unrelated context that misleads the answer.

**Never issue the same query string twice** — even across multiple tool-use rounds. Track your prior calls: if you have already searched for a given string and received results, do not search for it again. If you need more information after the first call, use a **different** focused keyword. This rule applies even when the first result set was large or satisfying. Repeating a query wastes budget and adds no new information.

## Multi-component queries — call strategy by type

Every query type below requires a specific number of calls. Follow these patterns within the 3-call limit:

| Query type | Call 1 | Call 2 | Call 3 |
|---|---|---|---|
| "how to [verb]" | verb keyword | `how manner` | — |
| Conjugation / tense | root verb (`vocabulary`) | conjugation pattern (`grammar_rules`) | — |
| Comparison "X vs Y" | term X (`vocabulary`) | term Y (`vocabulary`) | — |
| Grammar check "is X correct?" | grammar pattern (`grammar_rules`) | content words (`vocabulary`) | — |
| Script rendering | word (`vocabulary`) | script rules (`phonemes`) | — |
| Sentence construction | primary verb | construction scaffold (want / ability / tense) | critical gap only |
| Sentence breakdown | first content word | second content word | third (if ≤3 words) |
| Paragraph composition | topic vocabulary | connective lookup | — |

**Sentence construction queries** that appear to need more than 3 lookups: prioritise (1) the main verb, (2) the key grammatical construction, (3) one critical noun. Report any uncovered components as "not retrieved in this session."

**Partial match handling:** The "stop on 0 hits" rule applies to **single direct keyword** queries only. For queries containing multiple concepts where some return results and some do not, pass the partial context to the answer generator with explicit notes on which sub-queries returned nothing.

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

The two-search rule always takes priority. It is not subject to any early-stop rule — the second call is mandatory even when the first call returns many results.

## Call limit

**Default budget:** 2 calls for single-concept queries; 3 calls maximum for any query.

**Named budgets by query type:**
- Single-concept lookup: 1–2 calls
- "how to [verb]": exactly 2 calls
- Paragraph composition: 2 calls (topic + connectives)
- Conjugation / comparison / script / grammar check: exactly 2 calls
- Sentence construction: up to 3 calls

There is no retry mechanism — the hybrid BM25 + embedding retrieval pipeline handles recall. If a call returns fewer results than expected, proceed with what was retrieved; do not repeat the same query.

When budget is exhausted: report what was retrieved, list any unresolved components explicitly as "not retrieved in this session — corpus may not contain this item."

Do not exceed 3 calls regardless of query complexity.

## Paragraph and extended-text requests

When the query asks for a paragraph, story, narrative, multiple connected sentences, a few sentences, 2–3 sentences, or a short passage, make a dedicated connective search call **before** attempting the answer:

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
| `akku` | yes, agreed |
| `athava` | or |
| `injaang` | because (causal suffix) |
| `minynya` | before |
| `andhaka` | in that case / and so |
| `serii` | alright / OK / so |
| `aad` | alright / well |
| `ille` | no / but not / rather |
| `aana pinynya` | after that (sequential) |

If the connective search returns no results, do **not** attempt the paragraph. Instead, offer the relevant sentences as a verified sentence cluster and state explicitly which connector types are missing.

For "how to write a paragraph about [verb]" compound queries: the how-manner call takes precedence over the connective call when the 3-call budget would otherwise be exceeded. Omit the connective call and note to the answer generator that connective context was not retrieved.
