#!/usr/bin/env bash
# ============================================================
# deploy.sh — one-click deploy for knowledge-cli MCP service
#
# Usage:
#   ./deploy.sh              # deploy with default domain
#   DOMAIN=mcp.example.com ./deploy.sh
#
# Prerequisites:
#   - Docker + Docker Compose installed
#   - /home/deployer/knowledge/.env configured with API keys + NEO4J_PASSWORD
#   - /home/deployer/knowledge/data/ directory exists
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

# Load env vars into shell so ${NEO4J_PASSWORD} interpolation works
set -a
source "${ENV_FILE}"
set +a
export DOMAIN

# --- 1. Pull latest code ---
cd "${REPO_DIR}"
echo "[1/4] Pulling latest code..."

# The deploy host is a read-only mirror of origin/master: it must not carry
# any working-tree state that diverges from git. In practice the tree gets
# dirty through the normal ops rhythm — Caddyfile hand-tuned for a route,
# deploy/*.service created on the host before being committed, deploy.sh
# itself edited in place. Any of these breaks `git pull --ff-only` and stalls
# every subsequent deploy until someone logs in to clean up.
#
# So before pulling we force the working tree back to a pristine state:
#   git reset --hard  — discard ALL tracked modifications (repo is truth)
#   git clean -fd     — remove untracked files/dirs, but RESPECT .gitignore
#                       so server-only assets stay safe: .env (API keys),
#                       data/ (the SQLite knowledge base), .venv/, caches.
#
# This makes the "which files can drift?" question moot — the answer is
# "all of them, and they all get reconciled to the repo". --ff-only is kept
# so a genuine non-fast-forward (e.g. a force-push rewriting history) still
# fails loudly instead of silently merging.
git reset --hard HEAD
git clean -fd

git pull --ff-only origin master

# --- 2. Ensure data directory exists ---
mkdir -p /home/deployer/knowledge/data

# BuildKit needs proxy to pull base images from Docker Hub
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1}"

# --- 3. Rebuild & restart ---
echo "[2/4] Rebuilding and restarting services..."
docker compose --env-file "${ENV_FILE}" up -d --build --remove-orphans

# --- 3a. Restart Caddy to pick up bind-mounted config changes ---
# Caddyfile is bind-mounted; caddy reload reads from the container's
# filesystem which may be stale.  docker restart guarantees fresh mount.
echo "[2a] Restarting Caddy for config update..."
docker restart knowledge-caddy

# --- 4. Health check ---
echo "[3/4] Waiting for health checks..."
sleep 5

if docker compose ps | grep -q "unhealthy"; then
    echo "WARNING: Some services are unhealthy:"
    docker compose ps
    exit 1
fi

echo "[4/4] Cleaning up old images..."
docker image prune -f

echo ""
echo "=== Deploy complete ==="
docker compose ps
echo ""
echo "MCP endpoint: https://${DOMAIN}/mcp"
