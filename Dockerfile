# ============================================================
# Stage 1: Builder - install dependencies with uv
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.toml ./

# Install production dependencies only (project itself is not installed —
# at runtime we use `python -m src.cli` so source paths resolve correctly)
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

# Create data directory (src/paths.py resolves PROJECT_ROOT → /app, DB → /app/data/news.db)
RUN mkdir -p /app/data

# Default: MCP server (override CMD for ingestion:
#   docker compose run --rm mcp python -m src.cli _run_offline --once)
ENTRYPOINT ["python", "-m", "src.cli"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
