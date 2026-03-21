#!/usr/bin/env bash
# sync.sh — commit and push thakk submodule + parent in one shot
#
# Usage:
#   ./scripts/sync.sh "corpus: add <word>"   # commit thakk changes then push both
#   ./scripts/sync.sh                        # push only (no commit)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THAKK="$ROOT/data/thakk"
MSG="${1:-}"

# ── 1. Commit changes in thakk (only if message provided) ────────────────────
cd "$THAKK"

if [[ -n "$MSG" ]]; then
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "→ committing thakk: $MSG"
        git add -A
        git commit -m "$MSG"
    else
        echo "→ thakk: nothing to commit"
    fi
else
    echo "→ thakk: skipping commit (no message)"
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
