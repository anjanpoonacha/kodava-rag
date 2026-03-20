#!/usr/bin/env python3
"""
Download audio from a YouTube URL and save it as an MP3.

Usage:
    python scripts/download_audio.py <youtube_url> [--name <output_name>]

Output:
    data/raw/audio/<name>.mp3
    (default name is the video title, slugified)

Example:
    python scripts/download_audio.py "https://www.youtube.com/watch?v=ep17AxP_Cog"
    python scripts/download_audio.py "https://www.youtube.com/watch?v=ep17AxP_Cog" --name session_04
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
AUDIO_DIR = ROOT / "data" / "raw" / "audio"


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug.strip("_")


def download(url: str, name: str | None) -> Path:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("yt-dlp is not installed. Run: pip install yt-dlp")
        sys.exit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve the output name from the video title if not provided
    if name:
        output_name = name
    else:
        probe_opts = {
            "quiet": True,
            "no_warnings": False,
            "simulate": True,
            "remote_components": ["ejs:github"],
        }
        with YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            output_name = slugify(info["title"])

    output_path = AUDIO_DIR / f"{output_name}.mp3"

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "outtmpl": str(AUDIO_DIR / f"{output_name}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
        "remote_components": ["ejs:github"],
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Download audio from a YouTube URL.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--name", help="Output filename stem (without extension)")
    args = parser.parse_args()

    output = download(args.url, args.name)
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
