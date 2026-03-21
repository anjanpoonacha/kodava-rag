FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# git needed at runtime to clone the thakk submodule on first startup
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (data/thakk and data/corpus excluded via .dockerignore)
COPY . .

# Non-root user
RUN addgroup --gid 1001 appgroup && \
    adduser --uid 1001 --gid 1001 --no-create-home --disabled-password appuser && \
    chown -R appuser:appgroup /app

RUN chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

# Clone thakk at startup, build corpus, then start the API
ENTRYPOINT ["/app/entrypoint.sh"]
