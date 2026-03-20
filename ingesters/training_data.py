"""Ingester for training_data/*.json and *.jsonl files from the thakk repo.

grammar_flags.json    → grammar_rule entries (wrong form + correction + rule)
transliteration.json  → phoneme entries (romanized + Devanagari + pronunciation hints)
conjugations.jsonl    → grammar_rule entries, one per (verb, tense) with full forms table
"""

from __future__ import annotations

import json
from pathlib import Path

from ingesters import BaseIngester, CorpusEntry, register


@register
class TrainingDataIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.parent.name == "training_data" and path.suffix in (
            ".json",
            ".jsonl",
        )

    def ingest(self, path: Path) -> list[CorpusEntry]:
        if path.name == "conjugations.jsonl":
            lines = [
                l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()
            ]
            data = [json.loads(l) for l in lines]
            return self._ingest_conjugations(data, path.name)
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "grammar_flags.json":
            return self._ingest_grammar_flags(data, path.name)
        if path.name == "transliteration.json":
            return self._ingest_transliteration(data, path.name)
        return []

    # ------------------------------------------------------------------

    def _ingest_grammar_flags(self, data: list[dict], source: str) -> list[CorpusEntry]:
        entries = []
        for item in data:
            out = item.get("output", {})
            wrong = (item.get("input") or "").strip()
            correct = (out.get("correct_form") or "").strip()
            if not wrong or not correct:
                continue

            # Collect rule text from flags list or top-level explanation
            flags = out.get("flags") or []
            rule_parts = [f.get("rule", "") for f in flags if f.get("rule")]
            exception_parts = [
                f.get("exception", "") for f in flags if f.get("exception")
            ]
            explanation_raw = out.get("explanation", "")

            parts = rule_parts
            if exception_parts:
                parts += [f"Exception: {e}" for e in exception_parts]
            if explanation_raw and explanation_raw not in parts:
                parts.append(explanation_raw)

            explanation = " ".join(p for p in parts if p).strip()[:500]

            entries.append(
                CorpusEntry(
                    type="grammar_rule",
                    kodava=correct,
                    devanagari=out.get("devanagari", ""),
                    kannada="",
                    english=wrong,
                    explanation=explanation,
                    confidence="verified",
                    source=source,
                    tags=["correction"],
                )
            )
        return entries

    def _ingest_conjugations(self, data: list[dict], source: str) -> list[CorpusEntry]:
        """One grammar_rule entry per (verb, tense) — full forms table in explanation."""
        entries = []
        for item in data:
            out = item.get("output", {})
            verb = (out.get("verb") or "").strip()
            tense = (out.get("tense") or "").strip()
            meaning = (out.get("meaning") or "").strip()
            forms = out.get("forms") or []
            if not verb or not forms:
                continue

            # Build a compact table: "naan: X | niin: Y | ..."
            form_parts = [
                f"{f['person']}: {f['kodava']}"
                for f in forms
                if f.get("person") and f.get("kodava")
            ]
            explanation = f"{verb} ({meaning}) — {tense} tense. " + " | ".join(
                form_parts
            )

            # kodava field = naan form (most commonly queried)
            naan_form = next(
                (f["kodava"] for f in forms if f.get("person") == "naan"), verb
            )
            # devanagari = naan form devanagari if present
            naan_devan = next(
                (f.get("devanagari", "") for f in forms if f.get("person") == "naan"),
                "",
            )

            entries.append(
                CorpusEntry(
                    type="grammar_rule",
                    kodava=naan_form,
                    devanagari=naan_devan,
                    kannada="",
                    english=f"{tense} tense of {verb} — {meaning}",
                    explanation=explanation[:600],
                    confidence="textbook",
                    source=source,
                    tags=[f"verb:{verb}", f"tense:{tense}"],
                )
            )
        return entries

    def _ingest_transliteration(
        self, data: list[dict], source: str
    ) -> list[CorpusEntry]:
        entries = []
        for item in data:
            out = item.get("output", {})
            kodava = (item.get("input") or "").strip()
            devanagari = (out.get("devanagari") or "").strip()
            if not kodava or not devanagari:
                continue

            # Build pronunciation hint from the sounds list
            sounds = out.get("pronunciation") or []
            hint_parts = [s.get("hint", "") for s in sounds if s.get("hint")]
            explanation = "; ".join(hint_parts)[:400] if hint_parts else ""

            entries.append(
                CorpusEntry(
                    type="phoneme",
                    kodava=kodava,
                    devanagari=devanagari,
                    kannada="",
                    english=kodava,
                    explanation=explanation,
                    confidence="textbook",
                    source=source,
                    tags=[],
                )
            )
        return entries
