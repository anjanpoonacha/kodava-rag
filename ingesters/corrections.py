from __future__ import annotations
from pathlib import Path
from ingesters import BaseIngester, CorpusEntry, register


@register
class CorrectionsIngester(BaseIngester):
    def can_handle(self, path: Path) -> bool:
        return path.suffix == ".md" and "corrections" in path.name

    def ingest(self, path: Path) -> list[CorpusEntry]:
        entries = []
        lines = path.read_text(encoding="utf-8").splitlines()

        current: dict = {}

        def flush():
            if not current.get("what"):
                return
            wrong = current.get("what", "").strip()
            correct = current.get("correct", "").strip()
            why = current.get("why", "").strip()
            note = current.get("note", "").strip()
            confidence_raw = current.get("confidence", "").strip().lower()
            confidence = (
                "verified"
                if "certain" in confidence_raw or "confirmed" in confidence_raw
                else "textbook"
            )

            explanation = why or note

            if correct:
                entries.append(
                    CorpusEntry(
                        type="grammar_rule",
                        kodava=correct,
                        devanagari="",
                        kannada="",
                        english=wrong,
                        explanation=explanation,
                        confidence=confidence,
                        source=path.name,
                        tags=["correction"],
                    )
                )
            current.clear()

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- WHAT:"):
                flush()
                current["what"] = stripped[len("- WHAT:") :].strip()
            elif stripped.startswith("- CORRECT:"):
                current["correct"] = stripped[len("- CORRECT:") :].strip()
            elif stripped.startswith("- WHY:"):
                current["why"] = stripped[len("- WHY:") :].strip()
            elif stripped.startswith("- NOTE:"):
                current["note"] = stripped[len("- NOTE:") :].strip()
            elif stripped.startswith("- CONFIDENCE:"):
                current["confidence"] = stripped[len("- CONFIDENCE:") :].strip()
            elif stripped.startswith("- USAGE:"):
                current["usage"] = stripped[len("- USAGE:") :].strip()
            elif (
                current.get("what")
                and not stripped.startswith("-")
                and not stripped.startswith("#")
                and current.get("why") is not None
            ):
                if stripped:
                    current["why"] = (current.get("why", "") + " " + stripped).strip()

        flush()
        return entries
