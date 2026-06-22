"""One-shot backfill: clamp future-dated KnowledgeUnit event_time to published_at.

Background
----------
LLM extraction historically filled ``event_time`` with prediction / forecast
target years found inside the news text (e.g. "by 2030", "to 2100", "2025~2035").
``TimeNormalizer`` only soft-flagged those values, so they reached the DB:
161 KUs had ``event_time`` in the future relative to ``extracted_at``, poisoning
both the admin detail view and the derived cluster time anchors.

This was fixed at the source by hard-clamping future ``event_time`` to ``None``
in ``TimeNormalizer`` and falling back to ``published_at`` in
``KnowledgeExtractor``. This script repairs the existing bad rows and their
downstream derivatives.

Repair scope (three layers)
---------------------------
1. ``knowledge_units.event_time`` column + ``payload.time.event_time`` JSON
   → reset to the row's own ``published_at``; mark resolution ``contextual``.
   ``ku_id`` is intentionally NOT recomputed — it is the PK and a hash input,
   recomputing it would orphan every cluster/graph FK reference.
2. ``event_clusters`` derived from the affected KUs
   → recompute ``time_anchor`` / ``time_range`` / ``event_time_variants``
   from the corrected member KUs. ``conflict_status`` / ``conflict_details``
   / ``conflict_reasons`` are preserved: conflict is an independent dimension
   and recomputing it would invoke the LLM conflict detector for every
   multi-source cluster.
3. Neo4j ``:EventCluster`` nodes
   → re-sync the affected clusters via ``KnowledgeGraphSync``. Failures are
   non-fatal; the next ``run_continuous`` will re-sync them.

Usage
-----
    # Preview (default)
    uv run python scripts/fix_future_event_time.py --db data/news.db

    # Apply
    uv run python scripts/fix_future_event_time.py --db data/news.db --execute

Pre-flight: back up the DB first, e.g.
    cp data/news.db data/news.db.bak.$(date +%Y%m%d_%H%M%S)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime
from typing import Any

# KnowledgeUnit / EventCluster deserialization is needed to reuse the same
# anchor/variant derivation logic as the live pipeline.
from src.event_merging import AggregationVariant, EventCluster
from src.knowledge_base import KnowledgeUnit


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO datetime from a payload JSON value (str | datetime)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _anchor_datetime(unit: KnowledgeUnit) -> datetime:
    """Same anchor derivation as src.event_merging._anchor_datetime."""
    anchor = unit.time.event_time or unit.time.published_at
    return anchor if isinstance(anchor, datetime) else datetime.combine(
        anchor, datetime.min.time(), tzinfo=UTC
    )


def _explicit_event_date(unit: KnowledgeUnit) -> str | None:
    if unit.time.event_time is None:
        return None
    return unit.time.event_time.date().isoformat()


# ---------------------------------------------------------------------------
# Layer 1: KnowledgeUnit event_time column + payload
# ---------------------------------------------------------------------------


def _collect_future_kus(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows where event_time column is set and strictly later than extracted_at.

    Both columns are stored as ISO strings; string comparison works for ISO 8601
    with consistent offsets. A small grace window is not applied here because
    extracted_at is captured at extraction time and event_time is the event —
    any event_time strictly after extracted_at is by definition a future value.
    """
    return conn.execute(
        """
        SELECT ku_id, event_time, published_at, payload
        FROM knowledge_units
        WHERE event_time IS NOT NULL
          AND event_time > datetime('now')
        ORDER BY event_time DESC
        """
    ).fetchall()


def _fix_ku_row(row: sqlite3.Row) -> tuple[str, str, str]:
    """Return (ku_id, new_event_time_iso, new_payload_json) for one KU row.

    The new event_time is the row's own published_at (the report publication is
    the closest legitimate event time for a forward-looking statement).
    """
    payload = json.loads(row["payload"])
    published_iso = payload["time"]["published_at"]
    # Normalize to a comparable ISO string for the column value.
    published_dt = _parse_iso(published_iso)
    if published_dt is None:
        # Should not happen — published_at is a required field — but fall back
        # to the column value to avoid crashing the whole backfill.
        published_iso_col = row["published_at"]
    else:
        published_iso_col = published_dt.isoformat()

    payload["time"]["event_time"] = published_iso
    payload["time"]["event_time_resolution"] = "contextual"

    return row["ku_id"], published_iso_col, json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Layer 2: EventCluster time derivation (no LLM, no conflict recompute)
# ---------------------------------------------------------------------------


def _recompute_cluster_time_fields(
    cluster: EventCluster,
    member_units: list[KnowledgeUnit],
) -> EventCluster:
    """Recompute time_anchor / time_range / event_time_variants in place.

    Logic mirrors src.event_merging.build_event_cluster_snapshot lines 228-260
    but deliberately omits the conflict / representative / LLM branches so the
    backfill does not invoke the LLM conflict detector.
    """
    deduped = list({u.ku_id: u for u in member_units}.values())
    if not deduped:
        return cluster

    explicit_times = [u.time.event_time for u in deduped if u.time.event_time is not None]
    if explicit_times:
        anchor: datetime | date | None = min(explicit_times)
    else:
        anchor = min(u.time.published_at for u in deduped)

    anchor_values = [_anchor_datetime(u) for u in deduped]
    time_range = {
        "start": min(anchor_values).isoformat(),
        "end": max(anchor_values).isoformat(),
    }

    # Rebuild event_time_variants by explicit event date, same grouping rule
    # as build_event_cluster_snapshot (None event_time → skipped).
    time_groups: dict[str, list[KnowledgeUnit]] = {}
    for unit in deduped:
        event_date = _explicit_event_date(unit)
        if event_date is None:
            continue
        time_groups.setdefault(event_date, []).append(unit)

    variants = []
    for key, members in time_groups.items():
        if not key:
            continue
        rep = sorted(
            members,
            key=lambda unit: (
                -unit.confidence,
                -_anchor_datetime(unit).timestamp(),
                unit.ku_id,
            ),
        )[0]
        variants.append(
            AggregationVariant(
                value=_explicit_event_date(rep) or "",
                ku_ids=sorted({u.ku_id for u in members}),
                source_doc_ids=sorted({u.source.doc_id for u in members}),
                count=len(members),
            )
        )

    cluster.time_anchor = anchor
    cluster.time_range = time_range
    cluster.event_time_variants = variants
    cluster.updated_at = datetime.now(UTC)
    return cluster


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def run(db_path: str, *, dry_run: bool = True) -> dict[str, Any]:
    conn = _connect(db_path)
    stats: dict[str, Any] = {
        "future_kus": 0,
        "affected_clusters": 0,
        "neo4j_synced": 0,
        "neo4j_error": None,
    }

    # --- Layer 1: KU rows -----------------------------------------------
    future_rows = _collect_future_kus(conn)
    stats["future_kus"] = len(future_rows)

    affected_ku_ids: set[str] = {r["ku_id"] for r in future_rows}

    # --- Layer 2: find affected clusters --------------------------------
    # Two disjoint ways a cluster can be affected:
    #   (a) one of its member KUs had a future event_time;
    #   (b) its own time_anchor is already in the future but no member KU is
    #       (e.g. a previous partial fix, or a stale anchor left behind).
    # Catching both makes the backfill idempotent.
    affected_cluster_ids: set[str] = set()
    if affected_ku_ids:
        # Stage affected ku_ids into a temp table and match via json_each on
        # each cluster's payload — avoids building an N-way OR expression
        # (SQLite caps expression-tree depth at 1000; the remote prod DB has
        # 1200+ future KUs which blew up the OR approach).
        conn.execute("DROP TABLE IF EXISTS _tmp_future_ku_ids")
        conn.execute("CREATE TEMP TABLE _tmp_future_ku_ids (ku_id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO _tmp_future_ku_ids (ku_id) VALUES (?)",
            [(kuid,) for kuid in affected_ku_ids],
        )
        for row in conn.execute(
            """
            SELECT DISTINCT ec.cluster_id
            FROM event_clusters ec, json_each(ec.payload, '$.member_ku_ids') je
            WHERE je.value IN (SELECT ku_id FROM _tmp_future_ku_ids)
            """
        ).fetchall():
            affected_cluster_ids.add(row["cluster_id"])
    for row in conn.execute(
        "SELECT cluster_id FROM event_clusters WHERE time_anchor > datetime('now')"
    ).fetchall():
        affected_cluster_ids.add(row["cluster_id"])

    affected_cluster_rows: list[sqlite3.Row] = []
    if affected_cluster_ids:
        placeholders = ", ".join("?" for _ in affected_cluster_ids)
        affected_cluster_rows = conn.execute(
            f"SELECT cluster_id, payload FROM event_clusters WHERE cluster_id IN ({placeholders})",
            list(affected_cluster_ids),
        ).fetchall()
    stats["affected_clusters"] = len(affected_cluster_rows)

    # Dry run stops here — no writes, no Neo4j sync.
    if dry_run:
        conn.close()
        return stats

    # --- Apply Layer 1 --------------------------------------------------
    # Python's sqlite3 driver opens an implicit transaction on the SELECTs
    # above. Commit to close that read transaction before starting a write
    # transaction, otherwise BEGIN IMMEDIATE raises "cannot start a
    # transaction within a transaction".
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in future_rows:
            ku_id, new_event_time, new_payload = _fix_ku_row(row)
            conn.execute(
                """
                UPDATE knowledge_units
                SET event_time = ?, payload = ?, updated_at = CURRENT_TIMESTAMP
                WHERE ku_id = ?
                """,
                (new_event_time, new_payload, ku_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    # --- Apply Layer 2 --------------------------------------------------
    # Re-read affected clusters and their member units inside a fresh tx so
    # we see the corrected event_time values.
    rebuilt_clusters: list[EventCluster] = []
    if affected_cluster_rows:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for crow in affected_cluster_rows:
                cluster = EventCluster.model_validate(json.loads(crow["payload"]))
                # Load member KUs fresh (post-correction) via payload.
                placeholders = ", ".join("?" for _ in cluster.member_ku_ids)
                ku_rows = conn.execute(
                    f"SELECT payload FROM knowledge_units WHERE ku_id IN ({placeholders})",
                    cluster.member_ku_ids,
                ).fetchall()
                member_units = [KnowledgeUnit.model_validate(json.loads(r["payload"])) for r in ku_rows]
                if not member_units:
                    continue
                cluster = _recompute_cluster_time_fields(cluster, member_units)
                new_payload = json.dumps(cluster.model_dump(mode="json"), ensure_ascii=False)
                new_anchor = (
                    cluster.time_anchor.isoformat()
                    if isinstance(cluster.time_anchor, (datetime, date))
                    else None
                )
                conn.execute(
                    """
                    UPDATE event_clusters
                    SET time_anchor = ?, payload = ?, updated_at = ?
                    WHERE cluster_id = ?
                    """,
                    (new_anchor, new_payload, cluster.updated_at.isoformat(), cluster.cluster_id),
                )
                rebuilt_clusters.append(cluster)
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise

    conn.close()

    # --- Apply Layer 3: Neo4j -------------------------------------------
    if rebuilt_clusters:
        try:
            from src.knowledge_graph_sync import KnowledgeGraphSync

            KnowledgeGraphSync().sync(entities=[], clusters=rebuilt_clusters)
            stats["neo4j_synced"] = len(rebuilt_clusters)
        except Exception as exc:
            # Non-fatal: SQLite layers are already fixed. The next
            # run_continuous will re-sync Neo4j.
            stats["neo4j_error"] = f"{type(exc).__name__}: {exc}"

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clamp future-dated KnowledgeUnit event_time to published_at.",
    )
    parser.add_argument("--db", default="data/news.db", help="SQLite DB path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview only (default)",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Apply the changes",
    )
    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTING'}")
    if not args.dry_run:
        print("WARNING: this will mutate the database. Ensure you have a backup.")
    print()

    stats = run(args.db, dry_run=args.dry_run)

    print("Step 1 — Knowledge units:")
    print(f"  future event_time found: {stats['future_kus']}")
    print(f"  will reset to published_at: {stats['future_kus']}")
    print()
    print("Step 2 — Affected clusters:")
    print(f"  clusters to rebuild: {stats['affected_clusters']}")
    print()

    if args.dry_run:
        print("Step 3 — Neo4j sync:")
        print(f"  will sync {stats['affected_clusters']} clusters")
        print()
        print("Run with --execute to apply.")
        return 0

    print("Step 3 — Neo4j sync:")
    if stats["neo4j_error"]:
        print(f"  WARNING: sync failed — {stats['neo4j_error']}")
        print("  (SQLite layers are fixed; Neo4j will re-sync on next run_continuous)")
    else:
        print(f"  synced {stats['neo4j_synced']} clusters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
