"""Ingester for raw audio transcription files (*_transcription.txt).

Produces two entry types per transcription:
  1. Paragraph thread entries — one per topic section, confidence: audio_source
  2. Individual sentence entries — one per Kodava sentence, confidence: unverified

Translation is done via multi-agent parallel Claude calls: one agent per section
so each agent focuses on a coherent topic and all sections run concurrently.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import sys
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── parsing ───────────────────────────────────────────────────────────────────


def _extract_sections(text: str) -> list[tuple[str, list[str]]]:
    """Split transcription into (section_label, [kodava_sentences]) pairs.

    The transcription format uses **bold** for Kodava text and plain text for
    English narration. Structural breaks (question turns, blank lines between
    Kodava blocks, standalone English sentences) define section boundaries.
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_sentences: list[str] = []
    section_index = 0

    def _flush(sentences: list[str]) -> None:
        nonlocal section_index
        if len(sentences) >= 2:
            section_index += 1
            label = f"section_{section_index:02d}"
            sections.append((label, sentences[:]))

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Extract all bold Kodava phrases from this line
        bold_chunks = re.findall(r"\*\*(.+?)\*\*", stripped)
        if bold_chunks:
            # Filter to multi-word chunks (actual sentences, not single words)
            sentences_in_line = [c.strip() for c in bold_chunks if len(c.split()) >= 3]
            if sentences_in_line:
                current_sentences.extend(sentences_in_line)
                continue

        # Non-Kodava line: check if it's a substantial English paragraph
        # (not just "Thank you" or a one-word response)
        plain_words = re.sub(r"\*\*.*?\*\*", "", stripped).strip()
        if (
            plain_words
            and len(plain_words.split()) > 6
            and not re.search(r"\*\*", stripped)
        ):
            # Structural boundary — flush current section
            if current_sentences:
                _flush(current_sentences)
                current_sentences = []

    # Flush final section
    if current_sentences:
        _flush(current_sentences)

    return sections


# ── translation ───────────────────────────────────────────────────────────────

_TRANSLATE_PROMPT = """\
You are a Kodava Takk language expert. Translate the following numbered Kodava sentences to English.

Rules:
- Translate naturally — not word-for-word
- Preserve cultural terms (Kaavêri, Talakaveri, botth, kaNi pooje, etc.) in the translation
- Provide paragraph_english: a full, natural English translation of the ENTIRE passage as one coherent paragraph
- Provide per-sentence translations in the sentences array

Return ONLY valid JSON, no markdown fences:
{{
  "section": "{section_label}",
  "paragraph_english": "<full natural English translation of the whole passage>",
  "sentences": [
    {{"n": 1, "kodava": "...", "english": "..."}},
    ...
  ]
}}

Section: {section_label}
Kodava sentences:
{numbered_sentences}"""


def _translate_section(
    section_label: str,
    sentences: list[str],
    source_name: str,
) -> dict:
    """Translate one section via a single Claude call. Returns parsed JSON dict."""
    import anthropic as _anthropic
    import config as _config

    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    prompt = _TRANSLATE_PROMPT.format(
        section_label=section_label,
        numbered_sentences=numbered,
    )

    client = _anthropic.Anthropic(
        api_key=_config.ANTHROPIC_API_KEY,
        base_url=_config.ANTHROPIC_BASE_URL,
    )
    response = client.messages.create(
        model=_config.MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    block = response.content[0]
    raw = (block.text if hasattr(block, "text") else "").strip()  # type: ignore[attr-defined]

    # Strip markdown fences — model wraps in ```json\n...\n``` despite instructions
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return minimal structure so the ingester can continue
        return {
            "section": section_label,
            "paragraph_english": f"[Translation failed for section {section_label}]",
            "sentences": [
                {"n": i + 1, "kodava": s, "english": ""}
                for i, s in enumerate(sentences)
            ],
        }


_CHUNK_SIZE = 15  # max sentences per Claude call


def _chunk_section(label: str, sentences: list[str]) -> list[tuple[str, list[str]]]:
    """Split large sections into chunks of _CHUNK_SIZE sentences."""
    if len(sentences) <= _CHUNK_SIZE:
        return [(label, sentences)]
    chunks = []
    for i in range(0, len(sentences), _CHUNK_SIZE):
        chunk_label = f"{label}_chunk{i // _CHUNK_SIZE + 1:02d}"
        chunks.append((chunk_label, sentences[i : i + _CHUNK_SIZE]))
    return chunks


def _merge_chunks(label: str, chunk_results: list[dict]) -> dict:
    """Merge translation chunks back into a single section result."""
    all_sentences: list[dict] = []
    offset = 0
    for chunk in sorted(chunk_results, key=lambda r: r.get("section", "")):
        for item in chunk.get("sentences", []):
            all_sentences.append(
                {
                    "n": offset + item["n"],
                    "kodava": item["kodava"],
                    "english": item["english"],
                }
            )
        offset += len(chunk.get("sentences", []))

    # Combine paragraph_english from all chunks
    combined_english = " ".join(
        c.get("paragraph_english", "")
        for c in sorted(chunk_results, key=lambda r: r.get("section", ""))
        if c.get("paragraph_english") and not c["paragraph_english"].startswith("[")
    )
    return {
        "section": label,
        "paragraph_english": combined_english,
        "sentences": all_sentences,
    }


def _translate_all_sections(
    sections: list[tuple[str, list[str]]],
    source_name: str,
    max_workers: int = 8,
) -> list[dict]:
    """Translate all sections in parallel, chunking large sections. Returns translation dicts."""
    # Expand large sections into chunks
    jobs: list[tuple[str, str, list[str]]] = []  # (original_label, chunk_label, sents)
    for label, sents in sections:
        for chunk_label, chunk_sents in _chunk_section(label, sents):
            jobs.append((label, chunk_label, chunk_sents))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _translate_section, chunk_label, chunk_sents, source_name
            ): (orig_label, chunk_label)
            for orig_label, chunk_label, chunk_sents in jobs
        }
        chunk_results: dict[str, list[dict]] = {}
        for future in concurrent.futures.as_completed(futures):
            orig_label, chunk_label = futures[future]
            try:
                result = future.result()
                chunk_results.setdefault(orig_label, []).append(result)
            except Exception as exc:
                print(f"  WARN: translation failed for {chunk_label}: {exc}")
                chunk_results.setdefault(orig_label, []).append(
                    {
                        "section": chunk_label,
                        "paragraph_english": f"[Translation error: {exc}]",
                        "sentences": [],
                    }
                )

    # Merge chunks back into section results
    results = [
        _merge_chunks(label, chunk_results.get(label, [])) for label, _ in sections
    ]
    return results


# ── entry construction ─────────────────────────────────────────────────────────


def _make_thread_entry(
    section_label: str,
    kodava_sentences: list[str],
    paragraph_english: str,
    source_name: str,
    stem: str,
) -> CorpusEntry:
    topic_tag = section_label.replace("_", "-")
    return CorpusEntry(
        type="sentence",
        kodava=" ".join(kodava_sentences),
        devanagari="",
        kannada="",
        english=paragraph_english,
        explanation=(
            f"Paragraph thread from {source_name}. "
            f"Topic: {topic_tag}. "
            f"Native speaker audio. Contains connectives: pinynya, serii, aad, aachingi, en'ndu."
        ),
        confidence="audio_source",
        source=source_name,
        tags=["paragraph", stem, topic_tag, "connectives", "audio_source"],
    )


_LOW_QUALITY_PATTERNS = (
    "this video",
    "this is a kodava",
    "presentation",
    "placeholder",
    "untranslatable",
    "consists largely",
    "plain text",
    "let us learn",
    "we will learn",
    "in this video",
    "passage appears",
)


def _is_low_quality(english: str, kodava: str) -> bool:
    """Filter out meta-commentary and intro fragments that pollute the corpus."""
    e_lower = english.lower()
    if any(p in e_lower for p in _LOW_QUALITY_PATTERNS):
        return True
    # Skip entries where the Kodava is shorter than 4 words — likely a fragment
    if len(kodava.split()) < 4:
        return True
    return False


def _make_sentence_entry(
    kodava: str,
    english: str,
    source_name: str,
    stem: str,
    section_label: str,
) -> CorpusEntry:
    return CorpusEntry(
        type="sentence",
        kodava=kodava,
        devanagari="",
        kannada="",
        english=english,
        explanation=f"From {source_name}, section {section_label}.",
        confidence="unverified",
        source=source_name,
        tags=[stem, section_label, "audio_source"],
    )


# ── ingester ───────────────────────────────────────────────────────────────────


@register
class TranscriptionIngester(BaseIngester):
    """Ingests *_transcription.txt files into paragraph threads + sentence entries."""

    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".txt" and "_transcription" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        text = path.read_text(encoding="utf-8")
        source_name = path.name
        stem = path.stem.replace("_transcription", "")

        # Parse sections
        sections = _extract_sections(text)
        if not sections:
            print(f"  WARN: no sections found in {path.name}")
            return []

        print(f"  {path.name}: {len(sections)} sections, translating in parallel...")

        # Translate all sections concurrently
        translations = _translate_all_sections(sections, source_name)

        # Build a lookup: section_label → translation dict
        trans_map = {t["section"]: t for t in translations}

        entries: list[CorpusEntry] = []
        for section_label, kodava_sentences in sections:
            trans = trans_map.get(section_label, {})
            paragraph_english = trans.get("paragraph_english", "")
            sentence_translations = {
                item["n"]: item.get("english", "")
                for item in trans.get("sentences", [])
                if isinstance(item.get("n"), int)
            }

            # 1. Paragraph thread entry
            if kodava_sentences and paragraph_english:
                entries.append(
                    _make_thread_entry(
                        section_label,
                        kodava_sentences,
                        paragraph_english,
                        source_name,
                        stem,
                    )
                )

            # 2. Individual sentence entries
            for i, kodava in enumerate(kodava_sentences):
                english = sentence_translations.get(i + 1, "")
                if kodava and english and not _is_low_quality(english, kodava):
                    entries.append(
                        _make_sentence_entry(
                            kodava,
                            english,
                            source_name,
                            stem,
                            section_label,
                        )
                    )

        print(
            f"  {path.name}: produced {len(entries)} entries "
            f"({sum(1 for e in entries if 'paragraph' in e.tags)} threads, "
            f"{sum(1 for e in entries if 'paragraph' not in e.tags)} sentences)"
        )
        return entries
