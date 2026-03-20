"""
Sync source files from anjanpoonacha/thakk into the local data/ cache,
and write feedback entries back to thakk/corpus/ via the GitHub Contents API.

Read path:  raw.githubusercontent.com (no token needed for public repos)
Write path: api.github.com/repos/.../contents  (requires GITHUB_TOKEN with contents:write)
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
    "audio-vocab/kodava_part1_vocab_table.md": "vocab_tables/kodava_part1_vocab_table.md",
    "audio-vocab/Kodava_Thakk_Padipo_Session_11_vocab_table.md": "vocab_tables/Kodava_Thakk_Padipo_Session_11_vocab_table.md",
    "audio-vocab/learn_kodava_part10_vocab_table.md": "vocab_tables/learn_kodava_part10_vocab_table.md",
    "phoneme_table/kodava_devanagari_map.json": "phonemes/kodava_devanagari_map.json",
}


def _raw_url(repo_path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{config.GITHUB_REPO}"
        f"/{config.GITHUB_BRANCH}/{repo_path}"
    )


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


def _fetch_raw(repo_path: str) -> bytes:
    req = urllib.request.Request(_raw_url(repo_path), headers=_headers())
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def sync_source_files() -> None:
    """Download source files from thakk into local data/processed/ and data/corpus/ cache."""
    processed = config.DATA / "processed"
    corpus = config.DATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)

    for remote_path, local_rel in SOURCE_FILE_MAP.items():
        local = processed / local_rel
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(_fetch_raw(remote_path))

    # Overwrite corpus feedback files — thakk is the source of truth
    (corpus / "sentences.jsonl").write_bytes(_fetch_raw("corpus/sentences.jsonl"))
    (corpus / "review.jsonl").write_bytes(_fetch_raw("corpus/review.jsonl"))


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
