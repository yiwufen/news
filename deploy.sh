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
#   - /opt/knowledge/.env configured with API keys + NEO4J_PASSWORD
#   - /opt/knowledge/data/ directory exists
# ============================================================

set -euo pipefail

REPO_DIR="/opt/knowledge/repo"
ENV_FILE="/opt/knowledge/.env"
DOMAIN="${DOMAIN:-localhost}"

echo "=== knowledge-cli deploy ==="
echo "DOMAIN=${DOMAIN}"
echo ""

# --- 0. Verify env file ---
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} not found."
    echo "  cp /opt/knowledge/repo/.env.example ${ENV_FILE}"
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
git pull --ff-only origin master

# --- 2. Ensure data directory exists ---
mkdir -p /opt/knowledge/data

# --- 3. Rebuild & restart ---
echo "[2/4] Rebuilding and restarting services..."
docker compose --env-file "${ENV_FILE}" up -d --build --remove-orphans

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
