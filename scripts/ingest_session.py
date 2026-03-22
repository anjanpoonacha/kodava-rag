#!/usr/bin/env python3
"""
Full pipeline: YouTube URL → audio → transcription → vocab table → thakk repo → corpus.

Usage:
    python scripts/ingest_session.py <youtube_url> --name session_04 --category sessions
    python scripts/ingest_session.py <youtube_url> --name quiz_08 --category quizzes
    python scripts/ingest_session.py <youtube_url> --name kaveri_sankramana --category other

Steps:
    1. Download audio    → data/raw/audio/<name>.mp3
    2. Transcribe        → data/thakk/audio-vocab/<category>/<name>/transcription.md
    3. Build vocab table → data/thakk/audio-vocab/<category>/<name>/vocab_table.md
    4. Push to thakk     → anjanpoonacha/thakk audio-vocab/<category>/<name>/
    5. Rebuild corpus    → data/corpus/*.jsonl
"""

import argparse
import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import anthropic
from anthropic.types import TextBlock

from config import DATA, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL
import config
from core.prompts import load_prompt

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)


# ── helpers ──────────────────────────────────────────────────────────────────


def run(cmd: list[str], desc: str) -> None:
    print(f"  {desc}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr[:300]}")
        sys.exit(1)
    if result.stdout.strip():
        print(f"  {result.stdout.strip()[:200]}")


def push_to_thakk(local_path: Path, repo_path: str, message: str) -> str:
    """Push a file to anjanpoonacha/thakk via gh CLI. Returns commit SHA."""
    # Check if file already exists (need sha for update)
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{config.GITHUB_REPO}/contents/{repo_path}",
            "--jq",
            ".sha",
        ],
        capture_output=True,
        text=True,
    )
    sha = result.stdout.strip() if result.returncode == 0 else None

    content = base64.b64encode(local_path.read_bytes()).decode("ascii")

    payload: dict = {
        "message": message,
        "content": content,
        "branch": config.GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    tmp = Path("/tmp/_gh_push.json")
    tmp.write_text(json.dumps(payload))

    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PUT",
            f"repos/{config.GITHUB_REPO}/contents/{repo_path}",
            "--input",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    tmp.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  Push failed: {result.stderr[:300]}")
        sys.exit(1)

    commit_sha = json.loads(result.stdout)["commit"]["sha"]
    return commit_sha


def transcribe_audio(audio_path: Path, transcription_path: Path) -> None:
    """Transcribe audio via the configured Anthropic proxy (base64 audio document)."""
    import base64 as _b64

    audio_b64 = _b64.b64encode(audio_path.read_bytes()).decode("ascii")
    prompt = load_prompt("ingest_session_transcribe")

    # Build message as plain dicts — the proxy accepts raw JSON regardless of SDK types.
    messages = [  # type: ignore[var-annotated]
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "audio/mp3",
                        "data": audio_b64,
                    },
                },
            ],
        }
    ]

    response = client.messages.create(
        model=config.MODEL,
        max_tokens=8192,
        messages=messages,  # type: ignore[arg-type]
    )

    transcription_path.parent.mkdir(parents=True, exist_ok=True)
    text = next(
        (b.text for b in response.content if isinstance(b, TextBlock)),
        "",
    )
    transcription_path.write_text(text, encoding="utf-8")


# ── pipeline ─────────────────────────────────────────────────────────────────


THAKK_AUDIO_VOCAB = ROOT / "data" / "thakk" / "audio-vocab"
VALID_CATEGORIES = ("sessions", "quizzes", "other")


def ingest(
    url: str,
    name: str,
    category: str = "sessions",
    dry_run: bool = False,
    start: str | None = None,
    end: str | None = None,
) -> None:
    if category not in VALID_CATEGORIES:
        print(f"  ERROR: --category must be one of {VALID_CATEGORIES}")
        sys.exit(1)

    audio_dir = DATA / "raw" / "audio"
    per_video_dir = THAKK_AUDIO_VOCAB / category / name

    audio_path = audio_dir / f"{name}.mp3"
    transcription_path = per_video_dir / "transcription.md"
    vocab_path = per_video_dir / "vocab_table.md"
    repo_transcription_path = f"audio-vocab/{category}/{name}/transcription.md"
    repo_vocab_path = f"audio-vocab/{category}/{name}/vocab_table.md"

    per_video_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  Ingesting: {name}  ({category})")
    print(f"  URL:       {url}")
    print(f"  Output:    {per_video_dir.relative_to(ROOT)}")
    print(f"{'=' * 60}\n")

    # 1. Download
    if not audio_path.exists():
        print("Step 1/5 — Download audio")
        run(
            [
                sys.executable,
                str(ROOT / "scripts" / "download_audio.py"),
                url,
                "--name",
                name,
            ]
            + (["--start", start] if start else [])
            + (["--end", end] if end else []),
            f"Downloading {name}.mp3",
        )
        if not audio_path.exists():
            print(f"  ERROR: expected {audio_path}")
            sys.exit(1)
    else:
        print(f"Step 1/5 — Audio already exists: {audio_path.name}")
    print(f"  size: {audio_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 2. Transcribe → per-video directory
    if not transcription_path.exists():
        print("\nStep 2/5 — Transcribe audio")
        try:
            transcribe_audio(audio_path, transcription_path)
            print(
                f"  Written: {transcription_path.relative_to(ROOT)} "
                f"({transcription_path.stat().st_size} bytes)"
            )
        except RuntimeError as e:
            print(f"  {e}")
            print("  Skipping transcription — no transcription.md produced")
    else:
        print(
            f"\nStep 2/5 — Transcription already exists: {transcription_path.relative_to(ROOT)}"
        )

    # 3. Build vocab table → per-video directory
    if not vocab_path.exists():
        print("\nStep 3/5 — Build vocab table")
        if transcription_path.exists():
            run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "process_transcription.py"),
                    str(transcription_path),
                    "--output-dir",
                    str(per_video_dir),
                ],
                "Extracting vocab table",
            )
        else:
            print("  No transcription available — skipping vocab table")
            return
    else:
        print(
            f"\nStep 3/5 — Vocab table already exists: {vocab_path.relative_to(ROOT)}"
        )
    print(f"  size: {vocab_path.stat().st_size} bytes")

    if dry_run:
        print("\n  DRY RUN — skipping GitHub push and corpus rebuild")
        return

    # 4. Push both files to thakk
    print("\nStep 4/5 — Push to thakk")
    if transcription_path.exists():
        sha = push_to_thakk(
            transcription_path,
            repo_transcription_path,
            f"corpus: add {name} timestamped transcription",
        )
        print(f"  Pushed: {repo_transcription_path} → {sha[:12]}")
    sha = push_to_thakk(vocab_path, repo_vocab_path, f"corpus: add {name} vocab table")
    print(f"  Pushed: {repo_vocab_path} → {sha[:12]}")

    # 5. Rebuild corpus
    print("\nStep 5/5 — Rebuild corpus")
    run(
        [sys.executable, str(ROOT / "scripts" / "build_corpus.py")], "Rebuilding corpus"
    )

    print(f"\n✓ {name} ingested successfully\n")


def main():
    parser = argparse.ArgumentParser(description="Full session ingest pipeline.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--name", required=True, help="Output name stem, e.g. session_04"
    )
    parser.add_argument(
        "--category",
        default="sessions",
        choices=list(VALID_CATEGORIES),
        help="Video category (default: sessions)",
    )
    parser.add_argument(
        "--start", help="Start time (MM:SS or HH:MM:SS). Auto-detected from ?t= in URL."
    )
    parser.add_argument(
        "--end", help="End time (MM:SS or HH:MM:SS). Omit to download to end."
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip push and rebuild")
    args = parser.parse_args()
    ingest(
        args.url,
        args.name,
        category=args.category,
        dry_run=args.dry_run,
        start=args.start,
        end=args.end,
    )


if __name__ == "__main__":
    main()
