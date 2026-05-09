# ============================================================
# Stage 1: Builder - install dependencies with uv
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.toml ./

# Sync production dependencies (no dev, no project itself)
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY src/ src/
COPY collectors/ collectors/

# ============================================================
# Stage 2: Runtime - minimal image
# ============================================================
FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --from=builder /app/src /app/src
COPY --from=builder /app/collectors /app/collectors

# Ensure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Default database path (override with volume mount)
ENV DB_PATH=/app/data/news.db

# Create data directory
RUN mkdir -p /app/data

ENTRYPOINT ["knowledge-cli"]
CMD ["--help"]
