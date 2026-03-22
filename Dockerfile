# Always build for linux/amd64 — the Kyma cluster is amd64.
# Building on a Mac (arm64) without this flag produces exec format error at runtime.

# ── Builder: compile C extensions (httptools, etc.) ──────────────────────────
FROM --platform=linux/amd64 python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime: no compiler, no dev tools, no yt-dlp, no gRPC stack ─────────────
FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# git: needed at startup to clone the thakk submodule (entrypoint.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy only the compiled packages from the builder stage
COPY --from=builder /install /usr/local

# Copy application source
# (data/thakk, data/corpus, data/raw, *.mp3, dev scripts excluded via .dockerignore)
COPY . .

# Non-root user
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --no-create-home --disabled-password appuser && \
    chown -R appuser:appgroup /app

RUN chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
