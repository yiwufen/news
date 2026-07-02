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

# Some repo-tracked files are routinely modified on the server before their
# changes make it back into a commit (ops "live-first" workflow): Caddyfile
# gets hand-tuned for routes, deploy/*.service units are created on the host
# first and committed later. Their working-tree copy then diverges from HEAD
# and breaks `git pull --ff-only`, stalling every subsequent deploy.
#
# We reconcile these known files to HEAD before pulling. The repository is the
# source of truth for them; if the on-disk content already matches HEAD this
# is a no-op, and if it differs the repo version wins (the live change was
# either already committed back, or is being superseded by a newer commit).
git checkout -- Caddyfile
git checkout -- deploy/
# Remove any untracked files under deploy/ (e.g. a .service created on the
# host before being committed to the repo) that would otherwise collide with
# files the pull needs to write.
git clean -fd -- deploy/

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
