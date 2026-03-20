from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import hashlib


@dataclass
class CorpusEntry:
    type: str  # vocabulary | grammar_rule | phoneme | sentence
    kodava: str  # always romanized Kodava — never Devanagari or Kannada script
    devanagari: str  # Devanagari rendering, empty string if unknown
    kannada: (
        str  # Kannada script rendering, empty string if unknown (model fills on demand)
    )
    english: str  # English meaning or description
    explanation: str  # word-by-word breakdown or rule detail
    confidence: str  # verified | audio_source | textbook | unverified
    source: str  # filename this entry came from
    tags: list[str] = field(default_factory=list)  # lesson:9, tense:past, etc.

    @property
    def id(self) -> str:
        key = (
            f"{self.type}:{self.kodava.lower().strip()}:{self.english.lower().strip()}"
        )
        return hashlib.sha256(key.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "kodava": self.kodava,
            "devanagari": self.devanagari,
            "kannada": self.kannada,
            "english": self.english,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "source": self.source,
            "tags": self.tags,
        }


class BaseIngester:
    def can_handle(self, path: Path) -> bool:
        raise NotImplementedError

    def ingest(self, path: Path) -> list[CorpusEntry]:
        raise NotImplementedError


REGISTRY: list[BaseIngester] = []


def register(cls):
    REGISTRY.append(cls())
    return cls
