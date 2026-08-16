#!/usr/bin/env bash
# ============================================================
# deploy.sh — pull-only deploy for knowledge-cli MCP service
#
# Images are built and pushed to GHCR by CI (.github/workflows/ci.yml).
# This script never builds: it pulls the CI-pinned images and recreates
# containers, so what CI tested is exactly what production runs.
#
# Usage:
#   IMAGE_TAG=sha-<commit> ./deploy.sh   # CI path: deploy the tested commit
#   ./deploy.sh                          # manual: reuse persisted tag, else master
#
# Rollback:
#   IMAGE_TAG=sha-<old-commit> ./deploy.sh
#
# Prerequisites:
#   - Docker + Docker Compose installed
#   - /home/deployer/knowledge/.env configured with API keys + NEO4J_PASSWORD
#   - One-time: GHCR packages are created private by default even though the
#     repo is public — either flip them to public in GitHub package settings
#     (anonymous pulls then work), or `docker login ghcr.io` as deployer with
#     a read:packages PAT
# ============================================================

set -euo pipefail

REPO_DIR="/home/deployer/knowledge/repo"
ENV_FILE="/home/deployer/knowledge/.env"
DATA_DIR="/home/deployer/knowledge/data"
DOMAIN="${DOMAIN:-localhost}"

echo "=== knowledge-cli deploy ==="
echo "DOMAIN=${DOMAIN}"
echo ""

# --- 0. Verify env file ---
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} not found."
    echo "  cp /home/deployer/knowledge/repo/.env.example ${ENV_FILE}"
    echo "  Then edit ${ENV_FILE} with your API keys and passwords."
    exit 1
fi

# Caller-supplied IMAGE_TAG (CI passes sha-<commit>) must be captured before
# `set -a; source` below, which would re-export the stale persisted value.
REQUESTED_TAG="${IMAGE_TAG:-}"

# Load env vars into shell so ${NEO4J_PASSWORD} interpolation works
set -a
source "${ENV_FILE}"
set +a
export DOMAIN
IMAGE_TAG="${REQUESTED_TAG:-${IMAGE_TAG:-master}}"
export IMAGE_TAG

# Persist the deployed tag: the ingestion/fetch systemd units run
# `docker compose run --rm mcp ...` outside this script and must resolve
# the same image the service containers run.
if [ -n "${REQUESTED_TAG}" ]; then
    if grep -q '^IMAGE_TAG=' "${ENV_FILE}"; then
        sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${IMAGE_TAG}|" "${ENV_FILE}"
    else
        echo "IMAGE_TAG=${IMAGE_TAG}" >> "${ENV_FILE}"
    fi
fi

# --- 1. Pull latest code ---
cd "${REPO_DIR}"
echo "[1/4] Pulling latest code..."

# The deploy host is a read-only mirror of origin/master: it must not carry
# any working-tree state that diverges from git. In practice the tree gets
# dirty through the normal ops rhythm — deploy/*.service created on the host
# before being committed, deploy.sh itself edited in place. Any of these
# breaks `git pull --ff-only` and stalls every subsequent deploy until
# someone logs in to clean up.
#
# So before pulling we force the working tree back to a pristine state:
#   git reset --hard  — discard ALL tracked modifications (repo is truth)
#   git clean -fd     — remove untracked files/dirs, but RESPECT .gitignore
#                       so server-only assets stay safe: .env (API keys),
#                       data/ (the SQLite knowledge base), .venv/, caches.
#
# --ff-only is kept so a genuine non-fast-forward (e.g. a force-push
# rewriting history) still fails loudly instead of silently merging.
git reset --hard HEAD
git clean -fd

git pull --ff-only origin master

# --- 2. Ensure data directory exists ---
mkdir -p "${DATA_DIR}"

# --- 3. Pull pinned images & recreate containers ---
# Pulls go through the docker daemon: if ghcr.io is unreachable from the
# host, configure the proxy at the daemon level (systemd drop-in for
# docker.service) — shell-level HTTP_PROXY exports do not affect `pull`.
echo "[2/4] Pulling images (IMAGE_TAG=${IMAGE_TAG})..."
docker compose --env-file "${ENV_FILE}" pull mcp admin

echo "[2a] Recreating containers..."
docker compose --env-file "${ENV_FILE}" up -d --no-build --remove-orphans

# Caddy / cloudflared are NOT touched here: they run in the standalone infra
# compose (deploy/infra/ on the server), so app deploys never restart the
# shared proxy or interrupt fin-trace traffic.

# --- 4. Health check ---
echo "[3/4] Waiting for health checks..."
sleep 5

if docker compose --env-file "${ENV_FILE}" ps | grep -q "unhealthy"; then
    echo "WARNING: Some services are unhealthy:"
    docker compose --env-file "${ENV_FILE}" ps
    exit 1
fi

echo "[4/4] Cleaning up old images..."
docker image prune -f

echo ""
echo "=== Deploy complete ==="
docker compose --env-file "${ENV_FILE}" ps
echo ""
echo "MCP endpoint: https://${DOMAIN}/mcp"
