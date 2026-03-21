#!/usr/bin/env bash
# sync.sh — commit and push thakk submodule + parent in one shot
#
# Usage:
#   ./scripts/sync.sh "corpus: add <word>"          # custom message for thakk
#   ./scripts/sync.sh                               # auto-message from thakk diff

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THAKK="$ROOT/data/thakk"
MSG="${1:-}"

# ── 1. Commit any changes in the thakk submodule ─────────────────────────────
cd "$THAKK"

if ! git diff --quiet || ! git diff --cached --quiet; then
    if [[ -z "$MSG" ]]; then
        echo "Error: thakk has uncommitted changes — provide a commit message"
        echo "Usage: $0 \"corpus: add <word>\""
        exit 1
    fi
    echo "→ committing thakk: $MSG"
    git add -A
    git commit -m "$MSG"
else
    echo "→ thakk: nothing to commit"
fi

# ── 2. Update the submodule pointer in the parent ────────────────────────────
cd "$ROOT"

if ! git diff --quiet data/thakk; then
    THAKK_SHA=$(git -C "$THAKK" rev-parse --short HEAD)
    echo "→ updating submodule pointer → thakk@$THAKK_SHA"
    git add data/thakk
    git commit -m "thakk: update submodule → $THAKK_SHA"
else
    echo "→ parent: submodule pointer already up to date"
fi

# ── 3. Push — submodule first (on-demand), then parent ───────────────────────
echo "→ pushing..."
git push origin main

echo "✓ done"
