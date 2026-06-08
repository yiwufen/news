#!/usr/bin/env bash
# backup.sh — daily SQLite backup with 7-day rotation
# Neo4j is not backed up here; it can be rebuilt from SQLite via
#   docker exec knowledge-mcp python -c "
#     from src.entities import EntityRepository
#     from src.event_merging import EventClusterRepository
#     from src.knowledge_graph_sync import KnowledgeGraphSync
#     from src.paths import DEFAULT_DB_PATH
#     er = EntityRepository(DEFAULT_DB_PATH)
#     cr = EventClusterRepository(DEFAULT_DB_PATH)
#     KnowledgeGraphSync().sync(er.get_all(), cr.get_all())
#   "
set -euo pipefail

BACKUP_DIR="/home/deployer/knowledge/backups"
DATA_DIR="/home/deployer/knowledge/data"
RETENTION_DAYS=7

mkdir -p "${BACKUP_DIR}"

if [ -f "${DATA_DIR}/news.db" ]; then
    cp "${DATA_DIR}/news.db" "${BACKUP_DIR}/news-$(date +%Y%m%d).db"
    echo "[$(date)] SQLite backup: OK"
else
    echo "[$(date)] SQLite backup: SKIP (file not found)"
fi

find "${BACKUP_DIR}" -name "*.db" -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] Backup complete ($(du -sh "${BACKUP_DIR}" | cut -f1))"
