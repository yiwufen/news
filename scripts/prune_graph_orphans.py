"""One-shot prune of orphan Entity nodes in Neo4j.

Background
----------
``KnowledgeGraphSync.sync()`` only upserts Entity / EventCluster nodes; it has
no delete path. SQLite-side entity merges (``dedup_entities.py`` /
``merge_alias_entities.py``) delete duplicate entity rows, but the old
``entity_id`` survived in Neo4j as an orphan node, still wired to EventClusters
via INVOLVED_IN edges. Those stale edges pollute GraphRAG retrieval.

This script reconciles the graph against the SQLite source of truth by calling
``KnowledgeGraphSync.prune_orphans()`` with the current entity_ids. It is also
the verification that the new prune code path works end-to-end before the
pipeline starts calling it automatically on every run.

Usage
-----
    # Preview: count orphans, show what would be migrated/deleted (no writes)
    uv run python scripts/prune_graph_orphans.py --db data/news.db

    # Apply
    uv run python scripts/prune_graph_orphans.py --db data/news.db --execute

In the Docker container (remote):
    docker exec <mcp-container> python /app/scripts/prune_graph_orphans.py \\
        --db /app/data/news.db --execute

Pre-flight: back up Neo4j first (``neo4j-admin database dump`` or stop+snapshot
the container).
"""

from __future__ import annotations

import argparse
import sys

from src.entities import EntityRepository
from src.knowledge_graph_sync import KnowledgeGraphSync


def _pre_count(sync: KnowledgeGraphSync, live_ids: list[str]) -> int:
    """Count orphan nodes without mutating anything (best-effort)."""
    try:
        with sync.connection.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)
                WHERE NOT e.id IN $live_ids
                RETURN count(e) AS c
                """,
                live_ids=live_ids,
            )
            rows = result.data()  # type: ignore[attr-defined]
            return int(rows[0]["c"]) if rows else 0
    except Exception:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune orphan Entity nodes from Neo4j"
    )
    parser.add_argument("--db", default="data/news.db", help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview only (default)")
    parser.add_argument("--execute", dest="dry_run", action="store_false",
                        help="Apply the prune")
    args = parser.parse_args()

    repo = EntityRepository(args.db)
    live_ids = repo.get_all_ids()
    name_to_live_id = {
        e.canonical_name: e.entity_id for e in repo.get_all()
    }
    print(f"Database: {args.db}")
    print(f"SQLite live entities: {len(live_ids)}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTING'}")
    print()

    sync = KnowledgeGraphSync()
    orphan_before = _pre_count(sync, live_ids)
    if orphan_before < 0:
        print("Could not pre-count orphans (Neo4j unreachable?).")
        return 1
    print(f"Orphan Entity nodes detected: {orphan_before}")
    if orphan_before == 0:
        print("Nothing to prune. Graph is consistent with SQLite.")
        return 0
    print()

    if args.dry_run:
        print("Dry run only — no changes made.")
        print("Run with --execute to prune.")
        return 0

    if not args.dry_run:
        print("WARNING: this will mutate Neo4j. Ensure you have a backup.")

    result = sync.prune_orphans(live_ids, name_to_live_id=name_to_live_id)
    print()
    print("=== prune result ===")
    print(f"  orphan_count:   {result['orphan_count']}")
    print(f"  edges_migrated: {result['edges_migrated']}")
    print(f"  edges_merged:   {result['edges_merged']}")
    print(f"  nodes_deleted:  {result['nodes_deleted']}")
    if result["errors"]:
        print(f"  errors ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"    - {e}")

    # Post-verify
    orphan_after = _pre_count(sync, live_ids)
    print()
    print(f"Orphan nodes after prune: {orphan_after}")
    return 0 if not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
