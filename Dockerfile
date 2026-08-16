# ============================================================
# Stage 1: Builder - install dependencies with uv
# ============================================================
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy dependency manifests first for layer caching. uv.lock MUST be included:
# without it `uv sync` re-resolves pyproject constraints from scratch and can
# pick up brand-new major releases (mcp 2.0.0 broke `mcp.server.fastmcp`
# imports in CI-built images while local cached builds stayed on 1.27.1).
COPY pyproject.toml uv.toml uv.lock ./

# Install production dependencies only (project itself is not installed —
# at runtime we use `python -m src.cli` so source paths resolve correctly).
# --frozen: resolve strictly from uv.lock so the image matches the tested env.
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY src/ src/
COPY collectors/ collectors/
COPY scripts/ scripts/

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
COPY --from=builder /app/scripts /app/scripts
COPY docker/healthcheck.py /app/healthcheck.py

# Ensure venv is on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Create data directory (src/paths.py resolves PROJECT_ROOT → /app, DB → /app/data/news.db)
RUN mkdir -p /app/data

# Default: MCP server
# Override with other commands as needed:
#   docker compose run --rm mcp python -m src.cli _run_offline --once --full
#   docker compose run --rm mcp python -m collectors.eastmoney_crawler --limit 200 --db /app/data/news.db
#   docker compose run --rm mcp python scripts/reclassify_units.py --db /app/data/news.db --dry-run
#   docker compose run --rm mcp python scripts/reclassify_units.py --db /app/data/news.db --llm-relabel
CMD ["python", "-m", "src.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
