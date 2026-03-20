from __future__ import annotations
import json
from pathlib import Path
from ingesters import BaseIngester, CorpusEntry, register


@register
class PhonemeMapIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".json" and "devanagari_map" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries = []
        data = json.loads(path.read_text(encoding="utf-8"))

        for category, phonemes in data.get("phonemes", {}).items():
            for p in phonemes:
                kodava = p.get("kodava", "")
                devanagari = p.get("devanagari", "")
                kannada = p.get("kannada", "")
                hint = p.get("hint", "")
                confidence_raw = p.get("confidence", "⚠️")
                confidence = "verified" if confidence_raw == "✅" else "unverified"
                note = p.get("note", "")

                entries.append(
                    CorpusEntry(
                        type="phoneme",
                        kodava=kodava,
                        devanagari=devanagari,
                        kannada=kannada,
                        english=hint,
                        explanation=note,
                        confidence=confidence,
                        source=path.name,
                        tags=[f"phoneme_type:{p.get('type', category)}"],
                    )
                )

        for rule in data.get("suffix_rules", []):
            suffix = rule.get("suffix", "")
            meaning = rule.get("meaning", "")
            devanagari = rule.get("devanagari", "")
            kannada = rule.get("kannada", "")
            example = rule.get("example", {})
            confidence_raw = rule.get("confidence", "⚠️")
            confidence = "verified" if confidence_raw == "✅" else "unverified"
            flag = rule.get("flag", "")
            explanation = flag
            if example:
                explanation += (
                    f" e.g. {example.get('kodava', '')} = {example.get('meaning', '')}"
                )

            entries.append(
                CorpusEntry(
                    type="phoneme",
                    kodava=suffix,
                    devanagari=devanagari,
                    kannada=kannada,
                    english=meaning,
                    explanation=explanation.strip(),
                    confidence=confidence,
                    source=path.name,
                    tags=["suffix_rule"],
                )
            )

        return entries
