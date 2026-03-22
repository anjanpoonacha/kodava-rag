#!/usr/bin/env python3
"""
Download audio from a YouTube URL and save it as an MP3.

Usage:
    python scripts/download_audio.py <youtube_url> [--name <output_name>]
    python scripts/download_audio.py <youtube_url> --start 0:47 --end 0:57 --name clip

Output:
    data/raw/audio/<name>.mp3
    (default name is the video title, slugified)

Time ranges:
    --start / --end accept MM:SS or HH:MM:SS (e.g. 0:47, 1:02:30).
    If the URL contains ?t=<seconds>, --start defaults to that value.
    Omit --end to download from --start to the end of the video.

Example:
    python scripts/download_audio.py "https://www.youtube.com/watch?v=ep17AxP_Cog"
    python scripts/download_audio.py "https://www.youtube.com/watch?v=ep17AxP_Cog" --name session_04
    python scripts/download_audio.py "https://youtu.be/8x4Sxqi-4UU?t=47" --end 0:57 --name clip
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent.parent
AUDIO_DIR = ROOT / "data" / "raw" / "audio"


def slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug.strip("_")


def seconds_to_mmss(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def extract_t_param(url: str) -> str | None:
    """Extract the t= (start seconds) param from a YouTube URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if "t" in params:
        try:
            return seconds_to_mmss(int(params["t"][0]))
        except (ValueError, IndexError):
            return params["t"][0]
    return None


def download(
    url: str,
    name: str | None,
    start: str | None = None,
    end: str | None = None,
) -> Path:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("yt-dlp is not installed. Run: pip install yt-dlp")
        sys.exit(1)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # Auto-detect --start from ?t= in the URL if not explicitly set
    if start is None:
        start = extract_t_param(url)

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

    # Trim to a time range if start/end specified
    if start:
        from yt_dlp.utils import download_range_func

        start_sec = int(_parse_ts(start))
        end_sec = int(_parse_ts(end)) if end else float("inf")
        ydl_opts["download_ranges"] = download_range_func(
            chapters=[],
            ranges=[(start_sec, end_sec)],  # type: ignore[arg-type]
        )
        ydl_opts["force_keyframes_at_cuts"] = True
        print(f"  Time range: {start} → {end or 'end'}")

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return output_path


def _parse_ts(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = [float(p) for p in ts.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def main():
    parser = argparse.ArgumentParser(description="Download audio from a YouTube URL.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--name", help="Output filename stem (without extension)")
    parser.add_argument(
        "--start", help="Start time (MM:SS or HH:MM:SS). Auto-detected from ?t= in URL."
    )
    parser.add_argument(
        "--end", help="End time (MM:SS or HH:MM:SS). Omit to download to end of video."
    )
    args = parser.parse_args()

    output = download(args.url, args.name, start=args.start, end=args.end)
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
