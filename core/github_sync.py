"""
Sync source files from anjanpoonacha/thakk into the local data/ cache,
and write feedback entries back to thakk/corpus/ via the GitHub Contents API.

Both reads and writes use api.github.com/repos/.../contents — never raw.githubusercontent.com,
which has CDN caching that can serve stale content for several minutes after a push.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

import config

# Maps thakk repo path → relative path under data/processed/
SOURCE_FILE_MAP: dict[str, str] = {
    "kodava_corrections.md": "corrections/kodava_corrections.md",
    # Kodava Thakk Padipo sessions
    "audio-vocab/session_01_vocab_table.md": "vocab_tables/session_01_vocab_table.md",
    "audio-vocab/session_02_vocab_table.md": "vocab_tables/session_02_vocab_table.md",
    "audio-vocab/session_03_vocab_table.md": "vocab_tables/session_03_vocab_table.md",
    "audio-vocab/session_04_vocab_table.md": "vocab_tables/session_04_vocab_table.md",
    "audio-vocab/session_05_vocab_table.md": "vocab_tables/session_05_vocab_table.md",
    "audio-vocab/session_06_vocab_table.md": "vocab_tables/session_06_vocab_table.md",
    "audio-vocab/session_07_vocab_table.md": "vocab_tables/session_07_vocab_table.md",
    "audio-vocab/session_08_vocab_table.md": "vocab_tables/session_08_vocab_table.md",
    "audio-vocab/session_09_vocab_table.md": "vocab_tables/session_09_vocab_table.md",
    "audio-vocab/session_10_vocab_table.md": "vocab_tables/session_10_vocab_table.md",
    "audio-vocab/session_12_vocab_table.md": "vocab_tables/session_12_vocab_table.md",
    "audio-vocab/kodava_part1_vocab_table.md": "vocab_tables/kodava_part1_vocab_table.md",
    "audio-vocab/Kodava_Thakk_Padipo_Session_11_vocab_table.md": "vocab_tables/Kodava_Thakk_Padipo_Session_11_vocab_table.md",
    "audio-vocab/learn_kodava_part10_vocab_table.md": "vocab_tables/learn_kodava_part10_vocab_table.md",
    # Kodava Padipu quizzes
    "audio-vocab/quiz_01_vocab_table.md": "vocab_tables/quiz_01_vocab_table.md",
    "audio-vocab/quiz_02_vocab_table.md": "vocab_tables/quiz_02_vocab_table.md",
    "audio-vocab/quiz_03_vocab_table.md": "vocab_tables/quiz_03_vocab_table.md",
    "audio-vocab/quiz_04_vocab_table.md": "vocab_tables/quiz_04_vocab_table.md",
    "audio-vocab/quiz_05_vocab_table.md": "vocab_tables/quiz_05_vocab_table.md",
    "audio-vocab/quiz_06_vocab_table.md": "vocab_tables/quiz_06_vocab_table.md",
    "audio-vocab/quiz_07_vocab_table.md": "vocab_tables/quiz_07_vocab_table.md",
    "audio-vocab/quiz_08_vocab_table.md": "vocab_tables/quiz_08_vocab_table.md",
    "audio-vocab/quiz_09_vocab_table.md": "vocab_tables/quiz_09_vocab_table.md",
    "audio-vocab/quiz_10_vocab_table.md": "vocab_tables/quiz_10_vocab_table.md",
    "audio-vocab/quiz_11_vocab_table.md": "vocab_tables/quiz_11_vocab_table.md",
    "audio-vocab/quiz_12_vocab_table.md": "vocab_tables/quiz_12_vocab_table.md",
    "audio-vocab/quiz_13_vocab_table.md": "vocab_tables/quiz_13_vocab_table.md",
    "audio-vocab/quiz_14_vocab_table.md": "vocab_tables/quiz_14_vocab_table.md",
    "audio-vocab/quiz_15_vocab_table.md": "vocab_tables/quiz_15_vocab_table.md",
    "audio-vocab/quiz_16_vocab_table.md": "vocab_tables/quiz_16_vocab_table.md",
    "audio-vocab/quiz_17_vocab_table.md": "vocab_tables/quiz_17_vocab_table.md",
    "audio-vocab/quiz_18_vocab_table.md": "vocab_tables/quiz_18_vocab_table.md",
    "audio-vocab/quiz_19_vocab_table.md": "vocab_tables/quiz_19_vocab_table.md",
    "audio-vocab/quiz_20_vocab_table.md": "vocab_tables/quiz_20_vocab_table.md",
    "audio-vocab/quiz_21_vocab_table.md": "vocab_tables/quiz_21_vocab_table.md",
    "audio-vocab/quiz_22_vocab_table.md": "vocab_tables/quiz_22_vocab_table.md",
    "audio-vocab/quiz_23_vocab_table.md": "vocab_tables/quiz_23_vocab_table.md",
    "audio-vocab/quiz_24_vocab_table.md": "vocab_tables/quiz_24_vocab_table.md",
    "audio-vocab/quiz_25_vocab_table.md": "vocab_tables/quiz_25_vocab_table.md",
    "audio-vocab/quiz_26_vocab_table.md": "vocab_tables/quiz_26_vocab_table.md",
    "audio-vocab/quiz_27_vocab_table.md": "vocab_tables/quiz_27_vocab_table.md",
    # Phoneme map
    "phoneme_table/kodava_devanagari_map.json": "phonemes/kodava_devanagari_map.json",
}


def _api_url(repo_path: str) -> str:
    return f"https://api.github.com/repos/{config.GITHUB_REPO}/contents/{repo_path}"


def _headers(write: bool = False) -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    elif write:
        raise RuntimeError("GITHUB_TOKEN is required for corpus write operations")
    return h


def _fetch_via_api(repo_path: str) -> bytes:
    """Fetch file content via GitHub Contents API — always returns current committed version.

    Used only for writes (to get current SHA). For bulk reads use _fetch_blob_map().
    """
    url = _api_url(repo_path)
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req) as resp:
        meta = json.loads(resp.read())
    return base64.b64decode(meta["content"].replace("\n", ""))


def _fetch_blob_map() -> dict[str, str]:
    """Fetch the full git tree in one API call → {path: blob_sha}.

    Single request instead of N individual contents calls — avoids secondary rate limits.
    """
    url = (
        f"https://api.github.com/repos/{config.GITHUB_REPO}"
        f"/git/trees/{config.GITHUB_BRANCH}?recursive=1"
    )
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req) as resp:
        tree = json.loads(resp.read())
    return {
        item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"
    }


def _fetch_blob(sha: str) -> bytes:
    """Fetch raw blob content by SHA — no per-file rate limit concerns."""
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/git/blobs/{sha}"
    req = urllib.request.Request(
        url, headers={**_headers(), "Accept": "application/vnd.github.raw+json"}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def sync_source_files() -> None:
    """Download source files from thakk into local data/processed/ and data/corpus/ cache.

    Uses a single git tree fetch + individual blob reads to avoid secondary rate limits.
    """
    processed = config.DATA / "processed"
    corpus = config.DATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)

    blob_map = _fetch_blob_map()

    all_paths = dict(SOURCE_FILE_MAP)
    all_paths["corpus/sentences.jsonl"] = None  # type: ignore[assignment]
    all_paths["corpus/review.jsonl"] = None  # type: ignore[assignment]

    for remote_path, local_rel in all_paths.items():
        if remote_path not in blob_map:
            print(f"  WARN: {remote_path} not found in thakk tree — skipping")
            continue
        content = _fetch_blob(blob_map[remote_path])
        if local_rel is not None:
            local = processed / local_rel
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
        else:
            # corpus files go directly to data/corpus/
            filename = remote_path.split("/")[-1]
            (corpus / filename).write_bytes(content)


def append_corpus_entry(repo_path: str, entry: dict) -> None:
    """Append one JSON line to a JSONL file in thakk via the GitHub Contents API.

    repo_path: path within the thakk repo, e.g. "corpus/sentences.jsonl"
    entry:     dict that will be serialised as a single JSON line
    """
    url = _api_url(repo_path)
    req = urllib.request.Request(url, headers=_headers(write=True))
    with urllib.request.urlopen(req) as resp:
        meta = json.loads(resp.read())

    current = base64.b64decode(meta["content"].replace("\n", ""))
    sha = meta["sha"]

    new_line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    updated = base64.b64encode(current + new_line).decode("ascii")

    payload = json.dumps(
        {
            "message": f"corpus: add {entry.get('type', 'entry')} via feedback",
            "content": updated,
            "sha": sha,
            "branch": config.GITHUB_BRANCH,
        }
    ).encode("utf-8")

    put_req = urllib.request.Request(
        url,
        data=payload,
        headers={**_headers(write=True), "Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(put_req):
        pass
