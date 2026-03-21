"""
Sync and write-back helpers for the thakk language data submodule.

sync_source_files()  — pulls latest thakk commits into data/thakk/ via git submodule
append_corpus_entry() — writes feedback entries back to thakk/corpus/ via the GitHub
                        Contents API (requires GITHUB_TOKEN; used by the feedback endpoint)
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import config


def sync_source_files() -> None:
    """Pull the latest thakk commits into the data/thakk submodule.

    Equivalent to: git submodule update --remote --merge data/thakk
    Run this before every corpus build to ensure the latest language data is used.
    """
    submodule = config.DATA / "thakk"
    if not submodule.exists():
        raise RuntimeError(
            "data/thakk submodule is missing — run: git submodule update --init data/thakk"
        )

    result = subprocess.run(
        ["git", "submodule", "update", "--remote", "--merge", "data/thakk"],
        cwd=submodule.parent.parent,  # repo root
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"submodule update failed:\n{result.stderr}")

    print(f"  thakk submodule updated to latest main")


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


def append_corpus_entry(repo_path: str, entry: dict) -> None:
    """Append one JSON line to a JSONL file in thakk via the GitHub Contents API.

    repo_path: path within the thakk repo, e.g. "corpus/sentences.jsonl"
    entry:     dict serialised as a single JSON line appended to the file

    Uses the GitHub API so the write goes directly to the remote without
    requiring a local submodule commit + push cycle.
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
