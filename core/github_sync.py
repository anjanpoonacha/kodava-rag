"""
Sync and write-back helpers for the thakk language data submodule.

sync_source_files()      — pulls latest thakk commits into data/thakk/
ensure_feedback_branch() — creates feedback/pending branch if missing
append_to_staging()      — writes feedback to .md + .jsonl on the feedback branch
ensure_open_pr()         — opens (or reuses) a PR from feedback/pending → main
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request

import config

_THAKK_REPO = "https://github.com/anjanpoonacha/thakk.git"
_MD_PATH = "corpus/feedback_pending.md"
_JSONL_PATH = "corpus/feedback_pending.jsonl"

_MD_HEADER = (
    "# Pending Feedback\n\n"
    "Entries staged by app users for native speaker review.  \n"
    "Merge this PR to promote these entries to the live corpus.\n\n"
    "| ID | Action | Query | Answer | Correction | Submitted |\n"
    "|---|---|---|---|---|---|\n"
)


# ---------------------------------------------------------------------------
# Submodule sync (unchanged)
# ---------------------------------------------------------------------------


def sync_source_files() -> None:
    """Ensure data/thakk/ is present and up to date.

    Local dev  — data/thakk is a git submodule: runs git submodule update --remote.
    Container  — data/thakk is absent (excluded from image): shallow-clones from GitHub.

    Set SKIP_THAKK_SYNC=1 to skip the remote update entirely (useful when the
    submodule has local commits that haven't been pushed yet).
    """
    import os

    if os.environ.get("SKIP_THAKK_SYNC"):
        print("  thakk sync skipped (SKIP_THAKK_SYNC set)")
        return

    submodule = config.DATA / "thakk"

    if not submodule.exists():
        print(f"  cloning thakk from {_THAKK_REPO} ...")
        result = subprocess.run(
            ["git", "clone", "--depth", "1", _THAKK_REPO, str(submodule)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")
        print("  thakk cloned")
        return

    result = subprocess.run(
        ["git", "submodule", "update", "--remote", "--merge", "data/thakk"],
        cwd=submodule.parent.parent,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("  thakk submodule update skipped (git unavailable)")
        return

    print("  thakk submodule updated to latest main")


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _api(
    path: str,
    *,
    method: str = "GET",
    data: dict | None = None,
    write: bool = False,
) -> dict | list | None:
    """Call the GitHub API for the configured thakk repo.

    Returns parsed JSON on success, ``None`` on 404.
    """
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/{path}"
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    elif write:
        raise RuntimeError("GITHUB_TOKEN is required for feedback write operations")

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    if body:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _get_file(repo_path: str, branch: str) -> tuple[str, str] | None:
    """Read a file's content and blob SHA from a specific branch.

    Returns ``(content_text, sha)`` or ``None`` if the file does not exist.
    """
    result = _api(f"contents/{repo_path}?ref={branch}")
    if not isinstance(result, dict):
        return None
    content = base64.b64decode(result["content"].replace("\n", "")).decode("utf-8")
    return content, result["sha"]


def _put_file(
    repo_path: str,
    content: str,
    sha: str | None,
    branch: str,
    message: str,
) -> None:
    """Create or update a file on a specific branch via the Contents API."""
    payload: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    _api(f"contents/{repo_path}", method="PUT", data=payload, write=True)


# ---------------------------------------------------------------------------
# Feedback staging — branch, file writes, PR management
# ---------------------------------------------------------------------------


def ensure_feedback_branch() -> tuple[str, bool]:
    """Create the feedback/pending branch from main if it is missing or stale.

    Returns ``(branch_sha, is_fresh)`` where *is_fresh* is True when the
    branch was just (re-)created — callers use this to reset the staging
    files rather than appending to leftovers from a previous merged batch.
    """
    branch = config.FEEDBACK_BRANCH
    ref = _api(f"git/ref/heads/{branch}")

    if isinstance(ref, dict):
        compare = _api(f"compare/main...{branch}")
        if isinstance(compare, dict) and compare.get("ahead_by", 0) == 0:
            # Branch exists but was already merged — delete and recreate
            _api(f"git/refs/heads/{branch}", method="DELETE", write=True)
        else:
            return ref["object"]["sha"], False

    # Create fresh branch from current main
    main_ref = _api("git/ref/heads/main")
    if not isinstance(main_ref, dict):
        raise RuntimeError("Cannot find main branch in thakk repo")

    result = _api(
        "git/refs",
        method="POST",
        data={
            "ref": f"refs/heads/{branch}",
            "sha": main_ref["object"]["sha"],
        },
        write=True,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Failed to create feedback branch")
    return result["object"]["sha"], True


def _sanitize_cell(text: str, max_len: int = 80) -> str:
    """Strip newlines and markdown formatting for a clean table cell."""
    text = text.replace("\n", " ").replace("\r", "")
    text = text.replace("|", "\\|")
    # Collapse repeated spaces left over from stripped newlines
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()[:max_len]


def _format_md_row(entry: dict) -> str:
    """Render one feedback entry as a markdown table row."""
    entry_id = entry["id"]
    action = entry.get("user_action", "unknown")
    ctype = entry.get("correction_type")
    label = f"{action} [{ctype}]" if ctype else action

    query = _sanitize_cell(entry.get("english", ""), 60)
    answer = _sanitize_cell(entry.get("original_answer", ""), 80)
    correction = _sanitize_cell(entry.get("correction", "") or "—", 40)
    submitted = entry.get("created_at", "")

    cells = [f"`{entry_id}`", label, query, answer, correction, submitted]
    return "| " + " | ".join(cells) + " |\n"


def _to_corpus_dict(entry: dict) -> dict:
    """Convert a feedback entry to a CorpusEntry-compatible dict for the JSONL."""
    return {
        "id": entry["id"],
        "type": "sentence",
        "kodava": entry.get("kodava", ""),
        "english": entry.get("english", ""),
        "devanagari": "",
        "kannada": "",
        "explanation": entry.get("explanation", ""),
        "confidence": "unverified",
        "source": "ui_feedback",
        "tags": entry.get("tags", []),
    }


def append_to_staging(entry: dict) -> None:
    """Write a feedback entry to .md and .jsonl on the feedback/pending branch.

    On a freshly (re-)created branch the staging files are reset to avoid
    showing already-merged entries from a previous batch.
    """
    branch = config.FEEDBACK_BRANCH
    _, is_fresh = ensure_feedback_branch()

    md_row = _format_md_row(entry)
    jsonl_line = json.dumps(_to_corpus_dict(entry), ensure_ascii=False) + "\n"
    commit_msg = f"feedback: stage {entry['id']} for review"

    # ── .md file ──
    existing_md = _get_file(_MD_PATH, branch)
    if existing_md and not is_fresh:
        md_content, md_sha = existing_md
        md_content += md_row
    else:
        md_sha = existing_md[1] if existing_md else None
        md_content = _MD_HEADER + md_row

    _put_file(_MD_PATH, md_content, md_sha, branch, commit_msg)

    # ── .jsonl file ──
    existing_jsonl = _get_file(_JSONL_PATH, branch)
    if existing_jsonl and not is_fresh:
        jsonl_content, jsonl_sha = existing_jsonl
        jsonl_content += jsonl_line
    else:
        jsonl_sha = existing_jsonl[1] if existing_jsonl else None
        jsonl_content = jsonl_line

    _put_file(_JSONL_PATH, jsonl_content, jsonl_sha, branch, f"{commit_msg} (data)")


def ensure_open_pr() -> str:
    """Open a PR from feedback/pending → main, or return the existing one.

    Returns the PR's HTML URL.
    """
    owner = config.GITHUB_REPO.split("/")[0]
    branch = config.FEEDBACK_BRANCH
    prs = _api(f"pulls?state=open&head={owner}:{branch}&base=main")

    if prs:
        return prs[0]["html_url"]

    result = _api(
        "pulls",
        method="POST",
        data={
            "title": "Kodava feedback — pending speaker review",
            "body": (
                "Feedback staged by app users.\n\n"
                "Review the entries in `corpus/feedback_pending.md`, then "
                "merge to promote them to the live corpus.\n\n"
                "After merging, trigger a rebuild via `POST /admin/rebuild` "
                "to make the new entries searchable."
            ),
            "head": branch,
            "base": "main",
        },
        write=True,
    )
    if not isinstance(result, dict):
        raise RuntimeError("Failed to create feedback PR")
    return result["html_url"]


# ---------------------------------------------------------------------------
# Mock mode — writes to local files instead of GitHub API
# ---------------------------------------------------------------------------

_MOCK_DIR = config.DATA / "corpus"
_MOCK_MD = _MOCK_DIR / "feedback_pending.md"
_MOCK_JSONL = _MOCK_DIR / "feedback_pending.jsonl"


def _mock_append_to_staging(entry: dict) -> None:
    """Write feedback to local files (no GitHub calls)."""
    _MOCK_DIR.mkdir(parents=True, exist_ok=True)

    md_row = _format_md_row(entry)
    if not _MOCK_MD.exists() or _MOCK_MD.stat().st_size == 0:
        _MOCK_MD.write_text(_MD_HEADER + md_row, encoding="utf-8")
    else:
        with open(_MOCK_MD, "a", encoding="utf-8") as f:
            f.write(md_row)

    jsonl_line = json.dumps(_to_corpus_dict(entry), ensure_ascii=False) + "\n"
    with open(_MOCK_JSONL, "a", encoding="utf-8") as f:
        f.write(jsonl_line)


def _mock_ensure_open_pr() -> str:
    """Return a placeholder PR URL pointing to the local .md file."""
    return f"file://{_MOCK_MD}"


# ---------------------------------------------------------------------------
# Public dispatch — picks real or mock based on FEEDBACK_MOCK
# ---------------------------------------------------------------------------

if config.FEEDBACK_MOCK:
    append_to_staging = _mock_append_to_staging  # type: ignore[assignment]
    ensure_open_pr = _mock_ensure_open_pr  # type: ignore[assignment]
