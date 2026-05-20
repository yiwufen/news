"""One-time migration: populate normalized_name, entity_aliases, entity_identifiers,
cluster_entity_map index tables from existing entity/cluster payloads.

Usage:
    uv run python scripts/migrate_normalized_indexes.py [--db data/news.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.entities import Entity, EntityRepository, normalize_entity_name
from src.event_clustering import EventCluster, EventClusterRepository, _hash_entity_ids


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure the new columns and tables exist (idempotent)."""
    er = EntityRepository.__new__(EntityRepository)
    cr = EventClusterRepository.__new__(EventClusterRepository)
    # Use the static _ensure_column helper
    EntityRepository._ensure_column(conn, "entities", "normalized_name", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_norm_name ON entities(normalized_name)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_aliases (
            entity_id TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            PRIMARY KEY (entity_id, normalized_alias)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entity_aliases_value ON entity_aliases(normalized_alias, entity_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_identifiers (
            entity_id TEXT NOT NULL,
            identifier_key TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            PRIMARY KEY (entity_id, identifier_key)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entity_identifiers_lookup ON entity_identifiers(identifier_key, identifier_value, entity_id)"
    )
    EventClusterRepository._ensure_column(conn, "event_clusters", "entity_set_hash", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cluster_entity_map (
            entity_id TEXT NOT NULL,
            cluster_id TEXT NOT NULL,
            cluster_type TEXT NOT NULL,
            entity_set_hash TEXT NOT NULL,
            PRIMARY KEY (entity_id, cluster_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cluster_entity_map_lookup ON cluster_entity_map(cluster_type, entity_set_hash, cluster_id)"
    )
    conn.commit()


def _backfill_entities(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Backfill normalized_name, entity_aliases, entity_identifiers."""
    rows = conn.execute(
        "SELECT entity_id, payload FROM entities"
    ).fetchall()

    norm_updates: list[tuple[str, str]] = []
    alias_rows: list[tuple[str, str]] = []
    ident_rows: list[tuple[str, str, str]] = []

    for row in rows:
        entity = Entity.model_validate(json.loads(row["payload"]))
        norm_name = normalize_entity_name(entity.canonical_name)
        norm_updates.append((norm_name or "", row["entity_id"]))
        for alias in entity.aliases:
            norm_alias = normalize_entity_name(alias)
            if norm_alias and norm_alias != norm_name:
                alias_rows.append((row["entity_id"], norm_alias))
        for key, value in entity.identifiers.items():
            ident_rows.append((row["entity_id"], key, value))

    print(f"  Entities: {len(rows)} total")
    print(f"  normalized_name updates: {len(norm_updates)}")
    print(f"  alias rows: {len(alias_rows)}")
    print(f"  identifier rows: {len(ident_rows)}")

    if dry_run:
        return len(rows)

    conn.executemany(
        "UPDATE entities SET normalized_name = ? WHERE entity_id = ?",
        norm_updates,
    )
    if alias_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO entity_aliases (entity_id, normalized_alias) VALUES (?, ?)",
            alias_rows,
        )
    if ident_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO entity_identifiers (entity_id, identifier_key, identifier_value) VALUES (?, ?, ?)",
            ident_rows,
        )
    conn.commit()
    return len(rows)


def _backfill_clusters(conn: sqlite3.Connection, dry_run: bool) -> int:
    """Backfill entity_set_hash and cluster_entity_map."""
    rows = conn.execute(
        "SELECT cluster_id, cluster_type, payload FROM event_clusters"
    ).fetchall()

    hash_updates: list[tuple[str, str]] = []
    map_rows: list[tuple[str, str, str, str]] = []

    for row in rows:
        cluster = EventCluster.model_validate(json.loads(row["payload"]))
        sorted_ids = sorted(cluster.entity_ids)
        entity_hash = _hash_entity_ids(sorted_ids)
        hash_updates.append((entity_hash, row["cluster_id"]))
        for eid in sorted_ids:
            map_rows.append((eid, row["cluster_id"], row["cluster_type"], entity_hash))

    print(f"  Clusters: {len(rows)} total")
    print(f"  entity_set_hash updates: {len(hash_updates)}")
    print(f"  map rows: {len(map_rows)}")

    if dry_run:
        return len(rows)

    conn.executemany(
        "UPDATE event_clusters SET entity_set_hash = ? WHERE cluster_id = ?",
        hash_updates,
    )
    if map_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO cluster_entity_map (entity_id, cluster_id, cluster_type, entity_set_hash) VALUES (?, ?, ?, ?)",
            map_rows,
        )
    conn.commit()
    return len(rows)


def migrate(db_path: str = "data/news.db", dry_run: bool = False) -> None:
    print(f"Database: {db_path}")
    if dry_run:
        print("DRY RUN — no changes will be written")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("Ensuring schema...")
    _ensure_schema(conn)

    print("Backfilling entities...")
    entity_count = _backfill_entities(conn, dry_run)

    print("Backfilling clusters...")
    cluster_count = _backfill_clusters(conn, dry_run)

    conn.close()

    print()
    print(f"Done. Processed {entity_count} entities, {cluster_count} clusters.")
    if dry_run:
        print("(Dry run — no changes were written)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/news.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    migrate(db_path=args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
