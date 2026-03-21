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

# Repo paths that are always excluded from corpus sync.
# Prefix matches: any path starting with a listed prefix is skipped.
# Exact matches: any path exactly equal to a listed entry is skipped.
_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "M/",
    "adapters/",
    "data/",
    "training_config/",
    "corpus/",  # handled separately as special corpus/* paths
)
_EXCLUDE_EXACT: frozenset[str] = frozenset(
    {
        "README.md",
        "test.sh",
        "train.sh",
    }
)

# Maps thakk directory prefix → local subdirectory under data/processed/
_DIR_MAP: dict[str, str] = {
    "audio-vocab/": "vocab_tables",
    "phoneme_table/": "phonemes",
    "training_data/": "training_data",
}
# Root-level files (no directory prefix) → local subdirectory
_ROOT_FILE_MAP: dict[str, str] = {
    "kodava_corrections.md": "corrections",
    "elementary_kodava_FINAL.md": "textbook",
}


def _should_include(path: str) -> bool:
    """Return True if a repo file path should be synced to data/processed/."""
    if path in _EXCLUDE_EXACT:
        return False
    for prefix in _EXCLUDE_PREFIXES:
        if path.startswith(prefix):
            return False
    # Must match a known directory or be a known root file
    for prefix in _DIR_MAP:
        if path.startswith(prefix):
            return True
    return path in _ROOT_FILE_MAP


def _local_rel(remote_path: str) -> str:
    """Map a thakk repo path to a relative path under data/processed/."""
    for prefix, subdir in _DIR_MAP.items():
        if remote_path.startswith(prefix):
            filename = remote_path[len(prefix) :]
            return f"{subdir}/{filename}"
    subdir = _ROOT_FILE_MAP[remote_path]
    filename = remote_path.split("/")[-1]
    return f"{subdir}/{filename}"


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

    Dynamically discovers all files matching known include patterns — no static file list
    to maintain. Any new file added to thakk under a known directory is picked up
    automatically. Uses a single git tree fetch + individual blob reads.
    """
    processed = config.DATA / "processed"
    corpus = config.DATA / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)

    blob_map = _fetch_blob_map()

    # Sync source files into data/processed/
    synced = 0
    for remote_path in blob_map:
        if not _should_include(remote_path):
            continue
        content = _fetch_blob(blob_map[remote_path])
        rel = _local_rel(remote_path)
        local = processed / rel
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(content)
        synced += 1

    # Sync corpus JSONL files from thakk into data/processed/corpus/
    # vocabulary and grammar_rules feed the ingestion pipeline as curated seed data.
    # sentences and review are written directly to data/corpus/ (preserved across builds).
    processed_corpus = processed / "corpus"
    processed_corpus.mkdir(parents=True, exist_ok=True)

    for corpus_path in (
        "corpus/vocabulary.jsonl",
        "corpus/grammar_rules.jsonl",
        "corpus/phonemes.jsonl",
    ):
        if corpus_path not in blob_map:
            print(f"  WARN: {corpus_path} not found in thakk tree — skipping")
            continue
        content = _fetch_blob(blob_map[corpus_path])
        filename = corpus_path.split("/")[-1]
        (processed_corpus / filename).write_bytes(content)

    for corpus_path in ("corpus/sentences.jsonl", "corpus/review.jsonl"):
        if corpus_path not in blob_map:
            print(f"  WARN: {corpus_path} not found in thakk tree — skipping")
            continue
        content = _fetch_blob(blob_map[corpus_path])
        filename = corpus_path.split("/")[-1]
        (corpus / filename).write_bytes(content)

    print(f"  synced {synced} source files")


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
