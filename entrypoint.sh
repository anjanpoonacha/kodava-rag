#!/usr/bin/env bash
set -euo pipefail

echo "==> Building corpus from thakk..."
python scripts/build_corpus.py

echo "==> Starting API..."
exec python -m uvicorn api.app:app --host 0.0.0.0 --port 8000
