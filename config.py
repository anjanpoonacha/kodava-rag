import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
DATA = ROOT / "data"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
MODEL = "claude-sonnet-4-6"
TOP_K = 12
BM25_CANDIDATES = 30
MAX_TOKENS = 2048
WORD_SEARCH_THRESHOLD = (
    3  # trigger token-level fan-out when phrase search returns fewer hits
)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "anjanpoonacha/thakk")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# Dense retrieval — OpenAI-compatible embeddings endpoint.
# LITELLM_BASE_URL must point to a base that serves POST /embeddings
# (i.e. the /v1 root for standard OpenAI-compatible proxies).
# Falls back to stripping /anthropic from ANTHROPIC_BASE_URL and appending /v1,
# which works when both LLM and embedding traffic share the same proxy host.
_raw_base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
LITELLM_BASE_URL = os.getenv(
    "LITELLM_BASE_URL",
    _raw_base.removesuffix("/anthropic") + "/v1",
)
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-large")
# Set EMBED_ENABLED=false to run BM25-only (CI, offline, cost control).
# Set EMBED_ENABLED=local to use a deterministic random projection for local
# testing without any API calls — vectors are reproducible but not semantic.
EMBED_ENABLED = os.getenv("EMBED_ENABLED", "true").lower()  # "true" | "false" | "local"

# System prompt hot-loading — fetch from GitHub on container startup.
# Set PROMPT_FETCH=false for local dev/CI to avoid network dependency.
PROMPT_REPO = os.getenv("PROMPT_REPO", "anjanpoonacha/kodava-rag")
PROMPT_BRANCH = os.getenv("PROMPT_BRANCH", "main")
PROMPT_FETCH = os.getenv("PROMPT_FETCH", "false").lower() == "true"
