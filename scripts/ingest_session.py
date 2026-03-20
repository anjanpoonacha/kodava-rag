#!/usr/bin/env python3
"""
Full pipeline: YouTube URL → audio → vocab table → thakk repo → corpus rebuild.

Usage:
    python scripts/ingest_session.py <youtube_url> --name session_04
    python scripts/ingest_session.py <youtube_url> --name session_04 --dry-run

Steps:
    1. Download audio  → data/raw/audio/<name>.mp3          (via download_audio.py)
    2. Transcribe      → data/raw/transcriptions/<name>.txt  (via Gemini / Claude)
    3. Build vocab     → audio-vocab/<name>_vocab_table.md   (via process_transcription.py)
    4. Push to thakk   → anjanpoonacha/thakk audio-vocab/
    5. Rebuild corpus  → data/corpus/*.jsonl
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

from config import DATA
import config
from core.prompts import load_prompt


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
    """Transcribe audio to text using the Gemini API directly."""
    try:
        import google.generativeai as genai
        import os

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        audio_file = genai.upload_file(str(audio_path), mime_type="audio/mp3")
        response = model.generate_content(
            [
                audio_file,
                load_prompt("ingest_session_transcribe"),
            ]
        )
        transcription_path.parent.mkdir(parents=True, exist_ok=True)
        transcription_path.write_text(response.text, encoding="utf-8")
    except ImportError:
        # Fallback: use Claude with the audio file path as context
        raise RuntimeError(
            "google-generativeai not installed. Run: pip install google-generativeai"
        )


# ── pipeline ─────────────────────────────────────────────────────────────────


def ingest(url: str, name: str, dry_run: bool = False) -> None:
    audio_dir = DATA / "raw" / "audio"
    transcription_dir = DATA / "raw" / "transcriptions"
    vocab_dir = Path("/tmp") / "kodava_vocab"

    audio_path = audio_dir / f"{name}.mp3"
    transcription_path = transcription_dir / f"{name}_transcription.txt"
    vocab_path = vocab_dir / f"{name}_vocab_table.md"
    repo_vocab_path = f"audio-vocab/{name}_vocab_table.md"

    print(f"\n{'=' * 60}")
    print(f"  Ingesting: {name}")
    print(f"  URL:       {url}")
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
            ],
            f"Downloading {name}.mp3",
        )
        if not audio_path.exists():
            print(f"  ERROR: expected {audio_path}")
            sys.exit(1)
    else:
        print(f"Step 1/5 — Audio already exists: {audio_path.name}")
    print(f"  size: {audio_path.stat().st_size / 1024 / 1024:.1f} MB")

    # 2. Transcribe
    if not transcription_path.exists():
        print("\nStep 2/5 — Transcribe audio")
        try:
            transcribe_audio(audio_path, transcription_path)
            print(
                f"  Written: {transcription_path.name} ({transcription_path.stat().st_size} bytes)"
            )
        except RuntimeError as e:
            print(f"  {e}")
            print(
                "  Skipping transcription — will build vocab table directly from audio path"
            )
    else:
        print(f"\nStep 2/5 — Transcription already exists: {transcription_path.name}")

    # 3. Build vocab table
    if not vocab_path.exists():
        print("\nStep 3/5 — Build vocab table")
        if transcription_path.exists():
            run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "process_transcription.py"),
                    str(transcription_path),
                ],
                "Extracting vocab table",
            )
            # process_transcription.py writes to data/processed/vocab_tables/ — move to audio-vocab/
            processed = (
                ROOT / "data" / "processed" / "vocab_tables" / f"{name}_vocab_table.md"
            )
            if processed.exists() and not vocab_path.exists():
                vocab_dir.mkdir(parents=True, exist_ok=True)
                vocab_path.write_bytes(processed.read_bytes())
                print(f"  Copied to: {vocab_path}")
        else:
            print("  No transcription available — skipping vocab table")
            return
    else:
        print(f"\nStep 3/5 — Vocab table already exists: {vocab_path.name}")
    print(f"  size: {vocab_path.stat().st_size} bytes")

    if dry_run:
        print("\n  DRY RUN — skipping GitHub push and corpus rebuild")
        return

    # 4. Push to thakk
    print("\nStep 4/5 — Push to thakk")
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
    parser.add_argument("--dry-run", action="store_true", help="Skip push and rebuild")
    args = parser.parse_args()
    ingest(args.url, args.name, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
