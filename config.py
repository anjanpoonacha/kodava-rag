import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
DATA = ROOT / "data"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
MODEL = "claude-sonnet-4-6"
TOP_K = 8
BM25_CANDIDATES = 20
WORD_SEARCH_THRESHOLD = (
    3  # trigger token-level fan-out when phrase search returns fewer hits
)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "anjanpoonacha/thakk")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
