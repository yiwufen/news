"""Backfill INVOLVED_IN edge attributes + generate direct edges from history.

After the edge-semantics rollout (role/scope/nature on INVOLVED_IN + 4 direct
edge types), existing graph data lacks the new attributes. This script re-syncs
the full corpus through KnowledgeGraphSync so that:

1. Every existing INVOLVED_IN edge gets role/scope/nature (computed from the
   participating entity's type and the cluster's type).
2. Direct Entity→Entity edges (OWNERSHIP/GOVERNANCE/COMMERCIAL/RISK) are
   generated from all historical relation_hints (with merge semantics).

Reads the full corpus from SQLite once, then calls sync() in batches. Direct
edges are aggregated across the whole corpus (not per-batch) to maximise merge
opportunities — but for memory safety on large corpora, units are passed in
batches; a direct edge seen across batches still collapses via MERGE.

Usage (run inside the container where Neo4j + .env are available):
    docker compose --env-file /home/deployer/knowledge/.env run --rm mcp \\
        python scripts/backfill_edge_attributes.py --db /app/data/news.db

    # Dry run — report counts only, write nothing to the graph
    python scripts/backfill_edge_attributes.py --db data/news.db --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.entities import Entity, EntityRepository
from src.event_merging import EventCluster, EventClusterRepository
from src.knowledge_base import KnowledgeUnit, KnowledgeUnitRepository
from src.knowledge_graph_sync import KnowledgeGraphSync


def load_corpus(
    db_path: str,
) -> tuple[list[Entity], list[EventCluster], list[KnowledgeUnit]]:
    """Load all entities, clusters, and units from SQLite."""
    entity_repo = EntityRepository(db_path)
    cluster_repo = EventClusterRepository(db_path)
    unit_repo = KnowledgeUnitRepository(db_path)

    entities = entity_repo.list_all() if hasattr(entity_repo, "list_all") else []
    if not entities:
        # Fallback: load via get_all / paginated if list_all missing
        entities = _load_all_entities(db_path)
    clusters = cluster_repo.list_all() if hasattr(cluster_repo, "list_all") else []
    if not clusters:
        clusters = _load_all_clusters(db_path)
    units = unit_repo.list_all() if hasattr(unit_repo, "list_all") else []
    if not units:
        units = _load_all_units(db_path)
    return entities, clusters, units


def _load_all_entities(db_path: str) -> list[Entity]:
    """Fallback bulk load via direct SQLite read."""
    import json

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT payload FROM entities").fetchall()
    conn.close()
    return [Entity.model_validate(json.loads(p)) for (p,) in rows]


def _load_all_clusters(db_path: str) -> list[EventCluster]:
    import json

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT payload FROM event_clusters").fetchall()
    conn.close()
    return [EventCluster.model_validate(json.loads(p)) for (p,) in rows]


def _load_all_units(db_path: str) -> list[KnowledgeUnit]:
    import json

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT payload FROM knowledge_units").fetchall()
    conn.close()
    return [KnowledgeUnit.model_validate(json.loads(p)) for (p,) in rows]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill edge attributes + generate direct edges"
    )
    parser.add_argument("--db", default="data/news.db")
    parser.add_argument("--dry-run", action="store_true", help="Report only")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Units per sync batch (direct edges merge across batches via MERGE)",
    )
    args = parser.parse_args()

    print(f"Loading corpus from {args.db}...")
    entities, clusters, units = load_corpus(args.db)
    print(
        f"  entities: {len(entities)}, clusters: {len(clusters)}, units: {len(units)}"
    )

    # Count relation_hints that would become direct edges (for dry-run reporting).
    from src.schemas.enums import normalize_relation_type

    direct_candidates = 0
    one_off = 0
    unresolved = 0
    for unit in units:
        for hint in unit.relation_hints:
            if not (hint.subject_entity_id and hint.object_entity_id):
                unresolved += 1
                continue
            mapped = normalize_relation_type(hint.relation_type)
            if mapped[0] is None:
                one_off += 1
            else:
                direct_candidates += 1
    print(
        f"  relation_hints: {direct_candidates} direct-edge candidates, "
        f"{one_off} one-off (skipped), {unresolved} unresolved (skipped)"
    )

    if args.dry_run:
        print("\nDry run — no changes written.")
        print(f"Would re-sync {len(clusters)} clusters (INVOLVED_IN attr refresh).")
        print(f"Would write ~{direct_candidates} direct-edge MERGE operations.")
        return

    # Sync in batches. Clusters/entities are passed every batch (idempotent via
    # MERGE); units are batched so direct-edge aggregation stays memory-bounded.
    sync = KnowledgeGraphSync()
    total_involved_edges = 0
    total_direct_created = 0
    total_direct_merged = 0

    # First pass: re-sync all clusters (refreshes INVOLVED_IN role/scope/nature).
    # Pass units=None here — direct edges are written in the batched second pass.
    print("\n--- Pass 1: refresh INVOLVED_IN edge attributes ---")
    # Chunk clusters to avoid one giant transaction.
    cluster_batch = 500
    for i in range(0, len(clusters), cluster_batch):
        chunk = clusters[i : i + cluster_batch]
        stats = sync.sync(entities, chunk)
        total_involved_edges += stats["edges_created"]
        if i % (cluster_batch * 4) == 0:
            print(f"  clusters {i}/{len(clusters)}...")
    print(f"  INVOLVED_IN edges refreshed: {total_involved_edges}")

    # Second pass: direct edges from relation_hints, units in batches.
    print("\n--- Pass 2: generate direct edges from relation_hints ---")
    for i in range(0, len(units), args.batch_size):
        chunk = units[i : i + args.batch_size]
        # Direct edges only need the units; pass empty clusters to skip the
        # INVOLVED_IN loop (already done in pass 1).
        stats = sync.sync([], [], units=chunk)
        total_direct_created += stats["direct_edges_created"]
        total_direct_merged += stats["direct_edges_merged"]
        if i % (args.batch_size * 4) == 0:
            print(f"  units {i}/{len(units)}...")

    print(
        f"\nDone. INVOLVED_IN refreshed: {total_involved_edges}, "
        f"direct edges created: {total_direct_created}, merged: {total_direct_merged}"
    )


if __name__ == "__main__":
    main()
