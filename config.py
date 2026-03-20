import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SOURCE = Path(os.getenv("SOURCE_PATH", str(ROOT.parent / "thakk" / "source")))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"
TOP_K = 5
BM25_CANDIDATES = 20
