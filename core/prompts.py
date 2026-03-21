"""
Prompt loader with optional GitHub hot-loading.

load_prompt(name) tries sources in this order:
  1. GitHub raw URL  — when PROMPT_FETCH=true (default in production)
  2. Local file      — prompts/<name>.md inside the image (fallback)

This lets the system prompt be updated without rebuilding the Docker image:
  edit prompts/rag_assistant.md → git push main → kubectl rollout restart

Set PROMPT_FETCH=false (default) for local dev and CI to avoid network I/O.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/prompts/{name}.md"


def _fetch_remote(name: str) -> str | None:
    """Fetch a prompt from GitHub raw. Returns None on any failure."""
    from config import PROMPT_FETCH, PROMPT_REPO, PROMPT_BRANCH

    if not PROMPT_FETCH:
        return None

    url = _RAW_URL.format(repo=PROMPT_REPO, branch=PROMPT_BRANCH, name=name)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            content = resp.read().decode("utf-8").strip()
            logger.info("prompt '%s' loaded from %s", name, url)
            return content
    except urllib.error.HTTPError as exc:
        logger.warning(
            "prompt '%s' remote fetch failed: HTTP %s — using local file",
            name,
            exc.code,
        )
    except Exception as exc:
        logger.warning(
            "prompt '%s' remote fetch failed: %s — using local file", name, exc
        )

    return None


def load_prompt(name: str) -> str:
    """Load a prompt by name — GitHub first, local file fallback."""
    remote = _fetch_remote(name)
    if remote is not None:
        return remote

    path = PROMPTS_DIR / f"{name}.md"
    content = path.read_text(encoding="utf-8").strip()
    logger.debug("prompt '%s' loaded from local file", name)
    return content
