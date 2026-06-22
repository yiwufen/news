"""One-shot backfill: convert CST publish_time to UTC and repair extracted_at.

Background
----------
Two production-time bugs left the DB in an inconsistent temporal state:

1. **Crawler timezone bug.** ``collectors/eastmoney_crawler.py`` stored EastMoney's
   ``showTime`` (Beijing time, CST = UTC+8) verbatim into ``news_articles.publish_time``
   with no timezone marker. ``ensure_datetime`` then attached ``+00:00`` to the
   CST value, so every stored time is 8 hours ahead of true UTC. Admin list pages
   (``ORDER BY published_at DESC``) show these as "future".

2. **LLM-hallucinated extracted_at.** ``knowledge_extractor.py`` let the LLM fill
   ``time.published_at`` and ``time.extracted_at``. The LLM hallucinated values
   like ``extracted_at = 2025-01-18`` for 2026-06 articles, which broke
   ``TimeNormalizer``'s future-check baseline (extracted_at is the reference).

Both are fixed at the source now (crawler converts CST→UTC; extractor overwrites
system-owned time fields). This script repairs existing rows.

Repair scope
------------
* ``news_articles.publish_time`` — every row is space-separated CST (verified:
  18321/18321 rows). Subtract 8h, store as ``YYYY-MM-DD HH:MM:SS`` (UTC).
* ``knowledge_units.published_at`` (column + payload JSON) — re-derive from the
  corrected article ``publish_time`` via ``doc_id``.
* ``knowledge_units.event_time`` (column + payload JSON) — when it equals the
  pre-fix ``published_at`` (the extractor's future-clamp fallback or the
  "no time expression → published_at" rule), it inherited the CST error and
  must be re-aligned to the corrected ``published_at``.
* ``knowledge_units.extracted_at`` (column does not exist; payload only) — when
  implausible (in the future, or more than 30 days before/after ``published_at``),
  reset to ``published_at`` (a safe lower bound: extraction always happens after
  publication).
* ``event_clusters.time_anchor`` / ``time_range`` / ``event_time_variants``
  (column + payload) — recompute from corrected member KUs (no LLM, no conflict
  recompute, mirroring ``fix_future_event_time.py``).
* Neo4j ``:EventCluster`` nodes — re-sync affected clusters.

``ku_id`` is intentionally NOT recomputed (it is the PK and a hash input;
recomputing would orphan cluster / graph FK references).

Usage
-----
    # Preview (default)
    uv run python scripts/fix_timezone_and_extracted_at.py --db data/news.db

    # Apply
    uv run python scripts/fix_timezone_and_extracted_at.py --db data/news.db --execute

Pre-flight: back up the DB first, e.g.
    cp data/news.db data/news.db.bak.$(date +%Y%m%d_%H%M%S)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from src.event_merging import AggregationVariant, EventCluster
from src.knowledge_base import KnowledgeUnit

# EastMoney showTime is Beijing time (CST = UTC+8). Same offset as the crawler.
_CST = timezone(timedelta(hours=8))

# An extracted_at this far from published_at (either direction) is treated as a
# hallucination and reset. 30 days covers batching latency; real extraction
# always happens within hours-to-days of publication.
_EXTRACTED_AT_PLAUSIBLE_WINDOW = timedelta(days=30)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _parse_iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_cst_space_format(value: str) -> datetime | None:
    """Parse a space-separated CST datetime like '2026-06-22 16:17:11'."""
    s = value.strip()
    if not s or "T" in s:
        # Already ISO, or empty — leave to caller.
        return None
    fmt = "%Y-%m-%d %H:%M:%S" if len(s) == 19 else "%Y-%m-%d %H:%M"
    try:
        return datetime.strptime(s, fmt).replace(tzinfo=_CST).astimezone(UTC)
    except ValueError:
        return None


def _anchor_datetime(unit: KnowledgeUnit) -> datetime:
    anchor = unit.time.event_time or unit.time.published_at
    return anchor if isinstance(anchor, datetime) else datetime.combine(
        anchor, datetime.min.time(), tzinfo=UTC
    )


def _explicit_event_date(unit: KnowledgeUnit) -> str | None:
    if unit.time.event_time is None:
        return None
    return unit.time.event_time.date().isoformat()


# ---------------------------------------------------------------------------
# Layer 2 helper: recompute cluster time fields (no LLM, no conflict recompute)
# ---------------------------------------------------------------------------


def _recompute_cluster_time_fields(
    cluster: EventCluster,
    member_units: list[KnowledgeUnit],
) -> EventCluster:
    """Recompute time_anchor / time_range / event_time_variants in place.

    Mirrors src.event_merging.build_event_cluster_snapshot (lines 228-260) but
    omits conflict / representative / LLM branches so the backfill does not
    invoke the LLM conflict detector.
    """
    deduped = list({u.ku_id: u for u in member_units}.values())
    if not deduped:
        return cluster

    explicit_times = [u.time.event_time for u in deduped if u.time.event_time is not None]
    anchor: datetime | date | None = (
        min(explicit_times) if explicit_times
        else min(u.time.published_at for u in deduped)
    )

    anchor_values = [_anchor_datetime(u) for u in deduped]
    time_range = {
        "start": min(anchor_values).isoformat(),
        "end": max(anchor_values).isoformat(),
    }

    time_groups: dict[str, list[KnowledgeUnit]] = {}
    for unit in deduped:
        event_date = _explicit_event_date(unit)
        if event_date is None:
            continue
        time_groups.setdefault(event_date, []).append(unit)

    variants: list[AggregationVariant] = []
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
        "articles_converted": 0,
        "ku_published_at_fixed": 0,
        "ku_event_time_realigned": 0,
        "ku_extracted_at_reset": 0,
        "affected_clusters": 0,
        "neo4j_synced": 0,
        "neo4j_error": None,
    }

    # --- Layer 0: scan articles, build doc_id -> corrected publish_time map ---
    article_rows = conn.execute(
        "SELECT doc_id, publish_time FROM news_articles"
    ).fetchall()
    corrected_publish: dict[str, str] = {}
    for row in article_rows:
        pt = row["publish_time"]
        # Only convert space-separated CST values; ISO values (already fixed by
        # the new crawler) pass through unchanged.
        if " " in pt and "T" not in pt:
            converted = _parse_cst_space_format(pt)
            if converted is not None:
                # Store as ISO with explicit +00:00 offset. The "T" / "+"
                # markers distinguish already-converted UTC rows from raw CST
                # rows (which are space-separated with no offset), making the
                # script idempotent: re-running won't re-subtract 8 hours.
                corrected_publish[row["doc_id"]] = converted.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    stats["articles_converted"] = len(corrected_publish)

    # --- Layer 1: plan KU fixes -----------------------------------------
    ku_rows = conn.execute(
        "SELECT ku_id, doc_id, event_time, published_at, payload FROM knowledge_units"
    ).fetchall()

    ku_fixes: list[dict[str, Any]] = []
    affected_ku_ids: set[str] = set()
    for row in ku_rows:
        doc_id = row["doc_id"]
        payload = json.loads(row["payload"])
        old_pub_col = row["published_at"]
        old_pub_payload = payload["time"]["published_at"]
        old_evt = row["event_time"]
        old_evt_payload = payload["time"].get("event_time")
        old_ext = payload["time"].get("extracted_at")

        new_pub = corrected_publish.get(doc_id)
        if new_pub is None:
            continue  # article missing or already ISO — nothing to fix here

        new_pub_dt = _parse_iso(new_pub)
        if new_pub_dt is None:
            continue

        # Recompute derived fields.
        new_payload_pub = new_pub_dt.isoformat()

        # event_time realignment: if event_time currently equals the OLD
        # published_at (CST-tainted), it was set by the "no time expression"
        # rule or the future-clamp fallback — both inherited the CST error.
        # Re-align to the corrected published_at.
        new_evt = old_evt
        new_evt_payload = old_evt_payload
        evt_realigned = False
        if old_evt is not None and old_pub_col is not None:
            old_evt_dt = _parse_iso(old_evt)
            old_pub_dt = _parse_iso(old_pub_col)
            if old_evt_dt is not None and old_pub_dt is not None and old_evt_dt == old_pub_dt:
                new_evt = new_pub_dt.isoformat()
                new_evt_payload = new_pub_dt.isoformat()
                evt_realigned = True

        # extracted_at reset: implausible values → published_at (safe lower bound).
        new_ext = old_ext
        ext_reset = False
        if old_ext is not None:
            old_ext_dt = _parse_iso(old_ext)
            if old_ext_dt is not None:
                now = datetime.now(UTC)
                if old_ext_dt > now or abs(old_ext_dt - new_pub_dt) > _EXTRACTED_AT_PLAUSIBLE_WINDOW:
                    new_ext = new_pub_dt.isoformat()
                    ext_reset = True

        changed = (
            new_pub != old_pub_col
            or evt_realigned
            or ext_reset
        )
        if not changed:
            continue

        payload["time"]["published_at"] = new_payload_pub
        if "event_time" in payload["time"]:
            payload["time"]["event_time"] = new_evt_payload
        payload["time"]["extracted_at"] = new_ext
        # If event_time was realigned, keep resolution as contextual (report time).
        if evt_realigned:
            payload["time"]["event_time_resolution"] = "contextual"

        ku_fixes.append({
            "ku_id": row["ku_id"],
            "new_published_at": new_pub,
            "new_event_time": new_evt,
            "new_payload": json.dumps(payload, ensure_ascii=False),
            "evt_realigned": evt_realigned,
            "ext_reset": ext_reset,
        })
        affected_ku_ids.add(row["ku_id"])

    stats["ku_published_at_fixed"] = len(ku_fixes)
    stats["ku_event_time_realigned"] = sum(1 for f in ku_fixes if f["evt_realigned"])
    stats["ku_extracted_at_reset"] = sum(1 for f in ku_fixes if f["ext_reset"])

    # --- Layer 2: find affected clusters --------------------------------
    affected_cluster_ids: set[str] = set()
    if affected_ku_ids:
        conn.execute("DROP TABLE IF EXISTS _tmp_affected_ku_ids")
        conn.execute("CREATE TEMP TABLE _tmp_affected_ku_ids (ku_id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO _tmp_affected_ku_ids (ku_id) VALUES (?)",
            [(kuid,) for kuid in affected_ku_ids],
        )
        for row in conn.execute(
            """
            SELECT DISTINCT ec.cluster_id
            FROM event_clusters ec, json_each(ec.payload, '$.member_ku_ids') je
            WHERE je.value IN (SELECT ku_id FROM _tmp_affected_ku_ids)
            """
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

    if dry_run:
        conn.close()
        return stats

    # --- Apply Layer 0: articles ----------------------------------------
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for doc_id, new_pt in corrected_publish.items():
            conn.execute(
                "UPDATE news_articles SET publish_time = ? WHERE doc_id = ?",
                (new_pt, doc_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    # --- Apply Layer 1: knowledge_units ---------------------------------
    conn.execute("BEGIN IMMEDIATE")
    try:
        for fix in ku_fixes:
            conn.execute(
                """
                UPDATE knowledge_units
                SET published_at = ?, event_time = ?, payload = ?, updated_at = CURRENT_TIMESTAMP
                WHERE ku_id = ?
                """,
                (
                    fix["new_published_at"],
                    fix["new_event_time"],
                    fix["new_payload"],
                    fix["ku_id"],
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    # --- Apply Layer 2: clusters ----------------------------------------
    rebuilt_clusters: list[EventCluster] = []
    if affected_cluster_rows:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for crow in affected_cluster_rows:
                cluster = EventCluster.model_validate(json.loads(crow["payload"]))
                placeholders = ", ".join("?" for _ in cluster.member_ku_ids)
                ku_rows = conn.execute(
                    f"SELECT payload FROM knowledge_units WHERE ku_id IN ({placeholders})",
                    cluster.member_ku_ids,
                ).fetchall()
                member_units = [
                    KnowledgeUnit.model_validate(json.loads(r["payload"])) for r in ku_rows
                ]
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
            stats["neo4j_error"] = f"{type(exc).__name__}: {exc}"

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert CST publish_time to UTC and repair extracted_at.",
    )
    parser.add_argument("--db", default="data/news.db", help="SQLite DB path")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    parser.add_argument("--execute", dest="dry_run", action="store_false", help="Apply the changes")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTING'}")
    if not args.dry_run:
        print("WARNING: this will mutate the database. Ensure you have a backup.")
    print()

    stats = run(args.db, dry_run=args.dry_run)

    print("Layer 0 — Articles (CST → UTC):")
    print(f"  publish_time converted: {stats['articles_converted']}")
    print()
    print("Layer 1 — Knowledge units:")
    print(f"  published_at fixed:        {stats['ku_published_at_fixed']}")
    print(f"  event_time realigned:      {stats['ku_event_time_realigned']}")
    print(f"  extracted_at reset:        {stats['ku_extracted_at_reset']}")
    print()
    print("Layer 2 — Clusters:")
    print(f"  clusters to rebuild: {stats['affected_clusters']}")
    print()

    if args.dry_run:
        print("Layer 3 — Neo4j:")
        print(f"  will sync {stats['affected_clusters']} clusters")
        print()
        print("Run with --execute to apply.")
        return 0

    print("Layer 3 — Neo4j:")
    if stats["neo4j_error"]:
        print(f"  WARNING: sync failed — {stats['neo4j_error']}")
        print("  (SQLite layers are fixed; Neo4j will re-sync on next run_continuous)")
    else:
        print(f"  synced {stats['neo4j_synced']} clusters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
