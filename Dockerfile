# syntax=docker/dockerfile:1.7
# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Step 1: install only third-party dependencies (not the project itself).
# Copying only the lockfiles first maximises Docker layer cache — this layer
# is only invalidated when pyproject.toml or uv.lock change, not on code edits.
# NOTE: image is large (~5 GB) because sentence-transformers pulls in torch +
# CUDA packages via the lockfile. A CPU-only lockfile variant would reduce this.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra team --extra toml

# Step 2: copy source and install the project package on top.
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra team --extra toml

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user for least-privilege operation.
RUN useradd --create-home --no-log-init engram
USER engram
WORKDIR /home/engram

# Bring in the virtual-env from the builder stage.
COPY --from=builder --chown=engram:engram /app/.venv /app/.venv
COPY --from=builder --chown=engram:engram /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    # Bind to all interfaces inside the container; callers map the port.
    ENGRAM_HOST="0.0.0.0" \
    ENGRAM_PORT="7474" \
    # Persist SQLite DB to a named volume; overridden by ENGRAM_DB_URL for Postgres.
    ENGRAM_DB_PATH="/data/knowledge.db" \
    PYTHONUNBUFFERED="1"

# Data volume for SQLite mode. Unused when ENGRAM_DB_URL points to Postgres.
VOLUME ["/data"]

EXPOSE 7474

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:7474/api/health',timeout=4); sys.exit(0)"

CMD ["engram", "serve", "--http", \
     "--host", "0.0.0.0", \
     "--port", "7474"]
