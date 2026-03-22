"""
Build or refresh _manifest.yaml and per-video directory structure under
data/thakk/audio-vocab/.

Run this script once to migrate from the legacy flat layout to the
per-video directory layout.  It is safe to re-run — existing source.yaml
files and directories are never overwritten.

Usage:
    python scripts/build_manifest.py [--dry-run]
"""

import argparse
import re
import sys
from pathlib import Path

import yaml  # PyYAML — already in requirements (used by promptfoo)

THAKK_DIR = Path(__file__).parent.parent / "data" / "thakk"
VOCAB_DIR = THAKK_DIR / "audio-vocab"
MANIFEST = VOCAB_DIR / "_manifest.yaml"

# ---------------------------------------------------------------------------
# Static registry of all known source videos.
# Generated from the flat vocab_table.md headers on 2026-03-22.
# Add new entries here when a new video is ingested.
# ---------------------------------------------------------------------------
REGISTRY: list[dict] = [
    # ── sessions ────────────────────────────────────────────────────────────
    {
        "name": "session_01",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 1",
        "series": "kodava_thakk_padipo",
        "episode": 1,
        "url": "https://www.youtube.com/watch?v=O5PzmVM9Bh8",
        "audio_file": "data/thakk/source/audio/mp3/session_01.mp3",
    },
    {
        "name": "session_02",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 2 (Days of the Week)",
        "series": "kodava_thakk_padipo",
        "episode": 2,
        "url": "https://www.youtube.com/watch?v=sa-aDMuoYoo",
        "audio_file": "data/thakk/source/audio/mp3/session_02.mp3",
    },
    {
        "name": "session_03",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 3 (Greetings)",
        "series": "kodava_thakk_padipo",
        "episode": 3,
        "url": "https://www.youtube.com/watch?v=jRGsp66lnHo",
        "audio_file": "data/thakk/source/audio/mp3/session_03.mp3",
    },
    {
        "name": "session_04",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 4",
        "series": "kodava_thakk_padipo",
        "episode": 4,
        "url": "https://www.youtube.com/watch?v=ep17AxP_Cog",
        "audio_file": "data/thakk/source/audio/mp3/session_04.mp3",
    },
    {
        "name": "session_05",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 5",
        "series": "kodava_thakk_padipo",
        "episode": 5,
        "url": "https://www.youtube.com/watch?v=PibktL2nUzk",
        "audio_file": "data/thakk/source/audio/mp3/session_05.mp3",
    },
    {
        "name": "session_06",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 6",
        "series": "kodava_thakk_padipo",
        "episode": 6,
        "url": "https://www.youtube.com/watch?v=O9tdR9DYACg",
        "audio_file": "data/thakk/source/audio/mp3/session_06.mp3",
    },
    {
        "name": "session_07",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 7",
        "series": "kodava_thakk_padipo",
        "episode": 7,
        "url": "https://www.youtube.com/watch?v=5BBBwMB5PrE",
        "audio_file": "data/thakk/source/audio/mp3/session_07.mp3",
    },
    {
        "name": "session_08",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 8",
        "series": "kodava_thakk_padipo",
        "episode": 8,
        "url": "https://www.youtube.com/watch?v=7wllJQeD02k",
        "audio_file": "data/thakk/source/audio/mp3/session_08.mp3",
    },
    {
        "name": "session_09",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 9",
        "series": "kodava_thakk_padipo",
        "episode": 9,
        "url": "https://www.youtube.com/watch?v=AJ6xcpeEkxU",
        "audio_file": "data/thakk/source/audio/mp3/session_09.mp3",
    },
    {
        "name": "session_10",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 10",
        "series": "kodava_thakk_padipo",
        "episode": 10,
        "url": "https://www.youtube.com/watch?v=mYNvUTJPOtE",
        "audio_file": "data/thakk/source/audio/mp3/session_10.mp3",
    },
    {
        "name": "session_11",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 11",
        "series": "kodava_thakk_padipo",
        "episode": 11,
        "url": "https://www.youtube.com/watch?v=3u1HaVOnlFk",
        "audio_file": "data/thakk/source/audio/mp3/session_11.mp3",
    },
    {
        "name": "session_12",
        "category": "sessions",
        "title": "Kodava Thakk Padipo — Session 12 (Story: Adventures of Choondhu)",
        "series": "kodava_thakk_padipo",
        "episode": 12,
        "url": "https://www.youtube.com/watch?v=LHF1zk3SwS8",
        "audio_file": "data/thakk/source/audio/mp3/session_12.mp3",
    },
    # ── quizzes ─────────────────────────────────────────────────────────────
    {
        "name": "quiz_01",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 1 — Kodava Culture & Festivals",
        "series": "kodava_padipu",
        "episode": 1,
        "url": "https://www.youtube.com/watch?v=1ozH5UsgK20",
        "audio_file": "data/thakk/source/audio/mp3/quiz_01.mp3",
    },
    {
        "name": "quiz_02",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 2 — Kodava Flora, Kitchen & Culture",
        "series": "kodava_padipu",
        "episode": 2,
        "url": "https://www.youtube.com/watch?v=u-GjjjzPraU",
        "audio_file": "data/thakk/source/audio/mp3/quiz_02.mp3",
    },
    {
        "name": "quiz_03",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 3 — Kodava Professions / Occupations",
        "series": "kodava_padipu",
        "episode": 3,
        "url": "https://www.youtube.com/watch?v=nc8R2Rrj0-M",
        "audio_file": "data/thakk/source/audio/mp3/quiz_03.mp3",
    },
    {
        "name": "quiz_04",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 4 — Kodava Games, Culture & Traditions",
        "series": "kodava_padipu",
        "episode": 4,
        "url": "https://www.youtube.com/watch?v=alJT16SVA50",
        "audio_file": "data/thakk/source/audio/mp3/quiz_04.mp3",
    },
    {
        "name": "quiz_05",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 5 — Human Body Parts in Kodava Takk",
        "series": "kodava_padipu",
        "episode": 5,
        "url": "https://www.youtube.com/watch?v=H8-hAuLU8Ck",
        "audio_file": "data/thakk/source/audio/mp3/quiz_05.mp3",
    },
    {
        "name": "quiz_06",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 6 — Kodava Family Relationships (Chaache)",
        "series": "kodava_padipu",
        "episode": 6,
        "url": "https://www.youtube.com/watch?v=Je1JO42f7RI",
        "audio_file": "data/thakk/source/audio/mp3/quiz_06.mp3",
    },
    {
        "name": "quiz_07",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 7 — Kodava Nature, History & Architecture",
        "series": "kodava_padipu",
        "episode": 7,
        "url": "https://www.youtube.com/watch?v=mikPoo1Nifg",
        "audio_file": "data/thakk/source/audio/mp3/quiz_07.mp3",
    },
    {
        "name": "quiz_08",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 8 — Human Body Parts",
        "series": "kodava_padipu",
        "episode": 8,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_08.mp3",
    },
    {
        "name": "quiz_09",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 9 — Parts of a Traditional Kodava House",
        "series": "kodava_padipu",
        "episode": 9,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_09.mp3",
    },
    {
        "name": "quiz_10",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 10 — Kodava History, Culture & Geography",
        "series": "kodava_padipu",
        "episode": 10,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_10.mp3",
    },
    {
        "name": "quiz_11",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 11 — Household Items, Food & Nature",
        "series": "kodava_padipu",
        "episode": 11,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_11.mp3",
    },
    {
        "name": "quiz_12",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 12 — Clothing & Traditional Wear",
        "series": "kodava_padipu",
        "episode": 12,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_12.mp3",
    },
    {
        "name": "quiz_13",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 13 — Parts of the Ain Mane (Traditional House)",
        "series": "kodava_padipu",
        "episode": 13,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_13.mp3",
    },
    {
        "name": "quiz_14",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 14 — Traditional Kitchen Utensils & Vessels",
        "series": "kodava_padipu",
        "episode": 14,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_14.mp3",
    },
    {
        "name": "quiz_15",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 15 — Banana Varieties, Tools, Ceremonies & Festivals",
        "series": "kodava_padipu",
        "episode": 15,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_15.mp3",
    },
    {
        "name": "quiz_16",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 16 — Animals in Kodava Takk",
        "series": "kodava_padipu",
        "episode": 16,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_16.mp3",
    },
    {
        "name": "quiz_17",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 17 — Kaveri River Traditions & Kodava Festivals",
        "series": "kodava_padipu",
        "episode": 17,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_17.mp3",
    },
    {
        "name": "quiz_18",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 18 — Authentic Kodava Takk (Vocabulary Reclamation)",
        "series": "kodava_padipu",
        "episode": 18,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_18.mp3",
    },
    {
        "name": "quiz_19",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 19 — Geography, Colors, Aquatic Animals & Ceremonies",
        "series": "kodava_padipu",
        "episode": 19,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_19.mp3",
    },
    {
        "name": "quiz_20",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 20 — Authentic Kodava Takk Part 2",
        "series": "kodava_padipu",
        "episode": 20,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_20.mp3",
    },
    {
        "name": "quiz_21",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 21 — Kodava History, Culture & Geography",
        "series": "kodava_padipu",
        "episode": 21,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_21.mp3",
    },
    {
        "name": "quiz_22",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 22 — History, Wedding Traditions & Death Customs",
        "series": "kodava_padipu",
        "episode": 22,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_22.mp3",
    },
    {
        "name": "quiz_23",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 23 — Insects (Kodava Quest)",
        "series": "kodava_padipu",
        "episode": 23,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_23.mp3",
    },
    {
        "name": "quiz_24",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 24 — Cultural Knowledge",
        "series": "kodava_padipu",
        "episode": 24,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_24.mp3",
    },
    {
        "name": "quiz_25",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 25 — Three-Option Quiz",
        "series": "kodava_padipu",
        "episode": 25,
        "url": "https://www.youtube.com/watch?v=8x4Sxqi-4UU",
        "audio_file": "data/thakk/source/audio/mp3/quiz_25.mp3",
    },
    {
        "name": "quiz_26",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 26 — History & Cultural Trivia",
        "series": "kodava_padipu",
        "episode": 26,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_26.mp3",
    },
    {
        "name": "quiz_27",
        "category": "quizzes",
        "title": "Kodava Padipu Quiz 27 — Fruits in Kodava Takk",
        "series": "kodava_padipu",
        "episode": 27,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/quiz_27.mp3",
    },
    # ── other ────────────────────────────────────────────────────────────────
    {
        "name": "kaveri_sankramana",
        "category": "other",
        "title": "Kaveri Sankramana — Kodava Takk Cultural Video",
        "series": None,
        "episode": None,
        "url": "https://www.youtube.com/watch?v=oaqu4hZW_iw",
        "audio_file": "data/thakk/source/audio/mp3/kaveri_sankramana.mp3",
    },
    {
        "name": "kodava_part1",
        "category": "other",
        "title": "Learn Kodava Language Completely — Part 1",
        "series": "learn_kodava_completely",
        "episode": 1,
        "url": "https://www.youtube.com/watch?v=0xc6Kt3DMfY",
        "audio_file": "data/thakk/source/audio/mp3/kodava_part1.mp3",
    },
    {
        "name": "learn_kodava_part10",
        "category": "other",
        "title": "Learn Kodava Language Completely — Part 10 (Days, Time, Numbers)",
        "series": "learn_kodava_completely",
        "episode": 10,
        "url": None,
        "audio_file": "data/thakk/source/audio/mp3/days_of_week.mp3",
    },
    # ── Kodava Koota cultural videos ─────────────────────────────────────────
    {
        "name": "puthari",
        "category": "other",
        "title": "Puthari — Kodava Takk Cultural Video",
        "series": None,
        "episode": None,
        "url": "https://youtu.be/42sl3m-QdHs",
        "audio_file": "data/thakk/source/audio/mp3/puthari.mp3",
    },
    {
        "name": "kailpoudh",
        "category": "other",
        "title": "Kailpoudh — Kodava Takk Cultural Video",
        "series": None,
        "episode": None,
        "url": "https://www.youtube.com/watch?v=PfcH3hNupow",
        "audio_file": "data/thakk/source/audio/mp3/kailpoudh.mp3",
    },
    {
        "name": "kakkada_18",
        "category": "other",
        "title": "Kakkada 18 — Kodava Takk",
        "series": None,
        "episode": None,
        "url": "https://youtu.be/saYVku6IU3A",
        "audio_file": "data/thakk/source/audio/mp3/kakkada_18.mp3",
    },
    {
        "name": "edamyar_ondhe",
        "category": "other",
        "title": "Edamyar Ondhe — Kodava New Year",
        "series": None,
        "episode": None,
        "url": "https://youtu.be/0YpMD-vYbwY",
        "audio_file": "data/thakk/source/audio/mp3/edamyar_ondhe.mp3",
    },
]


def _source_yaml(entry: dict) -> str:
    """Render a source.yaml string for one registry entry."""
    lines = [f'title: "{entry["title"]}"']
    if entry.get("url"):
        lines.append(f'url: "{entry["url"]}"')
    else:
        lines.append("url: null  # not yet found — search by title")
    if entry.get("series"):
        lines.append(f"series: {entry['series']}")
    if entry.get("episode") is not None:
        lines.append(f"episode: {entry['episode']}")
    if entry.get("audio_file"):
        lines.append(f'audio_file: "{entry["audio_file"]}"')
    else:
        lines.append("audio_file: null  # not yet downloaded")
    lines.append("transcription_model: null  # fill after transcription")
    lines.append("transcription_date: null   # fill after transcription")
    return "\n".join(lines) + "\n"


def build(dry_run: bool = False) -> None:
    created_dirs = 0
    created_yamls = 0
    manifest_entries: list[dict] = []

    for entry in REGISTRY:
        out_dir = VOCAB_DIR / entry["category"] / entry["name"]
        source_yaml_path = out_dir / "source.yaml"

        manifest_entries.append(
            {
                "name": entry["name"],
                "category": entry["category"],
                "title": entry["title"],
                "url": entry.get("url"),
                "series": entry.get("series"),
                "episode": entry.get("episode"),
                "audio_file": entry.get("audio_file"),
                "has_transcription": (out_dir / "transcription.md").exists(),
                "has_vocab_table": (out_dir / "vocab_table.md").exists(),
            }
        )

        if not out_dir.exists():
            print(f"  mkdir  {out_dir.relative_to(THAKK_DIR.parent.parent)}")
            if not dry_run:
                out_dir.mkdir(parents=True, exist_ok=True)
            created_dirs += 1

        if not source_yaml_path.exists():
            print(f"  write  {source_yaml_path.relative_to(THAKK_DIR.parent.parent)}")
            if not dry_run:
                source_yaml_path.write_text(_source_yaml(entry), encoding="utf-8")
            created_yamls += 1

    # Write _manifest.yaml
    print(f"  write  {MANIFEST.relative_to(THAKK_DIR.parent.parent)}")
    if not dry_run:
        with MANIFEST.open("w", encoding="utf-8") as fh:
            yaml.dump(
                {"videos": manifest_entries},
                fh,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    total = len(REGISTRY)
    with_url = sum(1 for e in REGISTRY if e.get("url"))
    with_audio = sum(1 for e in REGISTRY if e.get("audio_file"))
    print(
        f"\nManifest: {total} videos | {with_url} with URL | {with_audio} with audio file"
    )
    print(f"Created:  {created_dirs} directories, {created_yamls} source.yaml files")
    if dry_run:
        print("(dry-run — no files written)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing anything",
    )
    args = parser.parse_args()
    build(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
