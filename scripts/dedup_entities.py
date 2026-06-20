"""Merge duplicate entities sharing the same normalized_name.

Replaces the earlier canonical_name-level dedup, which could not catch groups
that only collide after suffix stripping (e.g. "宇树科技" vs "宇树科技股份有限公司").

Grouping key is ``normalized_name`` (the ``entities.normalized_name`` column,
populated by ``EntityRepository.save_batch`` via ``normalize_entity_name``).
Within each group, the entity with the most source KUs (ties broken by shortest
canonical_name, then most recent update) is kept as primary; the rest are merged
into it and their references rewritten.

Usage:
    uv run python scripts/dedup_entities.py --db data/news.db [--dry-run|--execute]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone

from src.entities import normalize_entity_name

# Keep alias cap consistent with EntityResolver (src/entities.py).
_MAX_ALIASES = 10


def _utcnow_iso() -> str:
    """Return current UTC time in ISO 8601, matching Entity.updated_at format."""
    return datetime.now(timezone.utc).isoformat()


def dedup_entities(db_path: str, dry_run: bool = True) -> dict:
    """Merge duplicate entities and return summary stats.

    Groups by ``normalized_name``; within each group keeps one primary entity
    (most source_ku_ids, then shortest canonical_name, then newest) and merges
    the rest into it. Rewrites knowledge_units (both ``entity_ids`` column and
    ``payload.entities[].entity_id``) and ``cluster_entity_map`` references,
    rebuilds the primary's alias/identifier index rows, and deletes duplicates.
    All mutations run inside a single ``BEGIN IMMEDIATE`` transaction.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # Find duplicate groups by normalized_name (exclude NULL/empty).
    dup_groups = conn.execute("""
        SELECT normalized_name, COUNT(*) AS cnt
        FROM entities
        WHERE normalized_name IS NOT NULL AND normalized_name != ''
        GROUP BY normalized_name
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    stats = {
        "groups": len(dup_groups),
        "total_duplicates_removed": 0,
        "total_references_updated": 0,
        "details": [],
    }

    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")

    try:
        for normalized_name, _count in dup_groups:
            stats = _merge_one_group(conn, normalized_name, dry_run, stats)
    except Exception:
        if not dry_run:
            conn.rollback()
        conn.close()
        raise

    if not dry_run:
        conn.commit()
    conn.close()
    return stats


def _merge_one_group(
    conn: sqlite3.Connection,
    normalized_name: str,
    dry_run: bool,
    stats: dict,
) -> dict:
    """Merge all entities whose normalized_name == ``normalized_name``."""
    # Order within group: most source KUs first, then shortest canonical_name
    # (shortest canonical is usually the standard form, e.g. "比亚迪" over
    # "比亚迪股份有限公司"), then most recently updated.
    rows = conn.execute("""
        SELECT entity_id, canonical_name, entity_type, primary_identifier, payload
        FROM entities
        WHERE normalized_name = ?
        ORDER BY json_array_length(json_extract(payload, '$.source_ku_ids')) DESC,
                 LENGTH(canonical_name) ASC,
                 updated_at DESC
    """, (normalized_name,)).fetchall()

    if len(rows) < 2:
        return stats

    primary_id, primary_canonical, primary_type, primary_ident, primary_payload = rows[0]
    primary_payload = json.loads(primary_payload)
    duplicate_ids = [r[0] for r in rows[1:]]

    # Preserve the distinct canonical spellings being merged, for audit output.
    distinct_canonical_names = sorted({r[1] for r in rows})

    dup_payloads = {r[0]: json.loads(r[4]) for r in rows[1:]}

    # --- Field merge (normalized-level dedup for aliases) -------------------
    merged_aliases: list[str] = list(primary_payload.get("aliases", []))
    merged_identifiers: dict[str, str] = dict(primary_payload.get("identifiers", {}))
    merged_source_kus: list[str] = list(primary_payload.get("source_ku_ids", []))
    merged_tags: list[str] = list(primary_payload.get("tags", []))

    # Track aliases by normalized form so "比亚迪股份有限公司" and "比亚迪股份"
    # (which normalize identically) are not both kept.
    seen_alias_norms: set[str] = {
        normalize_entity_name(a) for a in merged_aliases if a
    }

    for dup_id in duplicate_ids:
        dup_payload = dup_payloads[dup_id]
        for alias in dup_payload.get("aliases", []):
            if len(merged_aliases) >= _MAX_ALIASES:
                break
            alias_norm = normalize_entity_name(alias)
            if alias and alias_norm not in seen_alias_norms:
                merged_aliases.append(alias)
                seen_alias_norms.add(alias_norm)
        for k, v in dup_payload.get("identifiers", {}).items():
            if k not in merged_identifiers:
                merged_identifiers[k] = v
        for ku_id in dup_payload.get("source_ku_ids", []):
            if ku_id not in merged_source_kus:
                merged_source_kus.append(ku_id)
        for tag in dup_payload.get("tags", []):
            if tag not in merged_tags:
                merged_tags.append(tag)

    # Count duplicates regardless of dry_run, so the summary reflects the
    # planned work even when no writes occur.
    stats["total_duplicates_removed"] += len(duplicate_ids)

    refs_updated = 0

    if not dry_run:
        now_iso = _utcnow_iso()
        primary_payload["aliases"] = merged_aliases
        primary_payload["identifiers"] = merged_identifiers
        primary_payload["source_ku_ids"] = merged_source_kus
        primary_payload["tags"] = merged_tags
        primary_payload["updated_at"] = now_iso

        primary_norm = normalize_entity_name(primary_canonical)
        primary_identifier_value = next(iter(merged_identifiers.values()), None)
        primary_payload_json = json.dumps(primary_payload, ensure_ascii=False)

        # Update primary entity — keep all indexed columns consistent with the
        # merged payload so idx_entities_name / idx_entities_norm_name stay valid.
        conn.execute("""
            UPDATE entities
            SET canonical_name = ?,
                entity_type = ?,
                primary_identifier = ?,
                normalized_name = ?,
                payload = ?,
                updated_at = ?
            WHERE entity_id = ?
        """, (
            primary_canonical, primary_type or "", primary_identifier_value,
            primary_norm, primary_payload_json, now_iso, primary_id,
        ))

        # Rewrite knowledge_units references for each duplicate.
        refs_updated = _rewrite_ku_references(conn, primary_id, duplicate_ids)

        # Rewrite cluster_entity_map (handles UNIQUE constraint).
        _rewrite_cluster_references(conn, primary_id, duplicate_ids)

        # Drop duplicate entities and their alias/identifier index rows.
        for dup_id in duplicate_ids:
            conn.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (dup_id,))
            conn.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (dup_id,))
            conn.execute("DELETE FROM entities WHERE entity_id = ?", (dup_id,))

        # Rebuild the primary's alias / identifier index rows so that aliases
        # merged in from duplicates become discoverable via the index tables
        # (matches EntityRepository.save_batch semantics).
        _rebuild_primary_indexes(
            conn, primary_id, primary_norm, merged_aliases, merged_identifiers
        )

    stats["total_references_updated"] += refs_updated

    stats["details"].append({
        "normalized_name": normalized_name,
        "canonical_names": distinct_canonical_names,
        "entity_type": primary_type,
        "duplicates_removed": len(duplicate_ids),
        "primary_id": primary_id,
        "primary_canonical": primary_canonical,
        "merged_source_ku_count": len(merged_source_kus),
    })
    return stats


def _rewrite_ku_references(
    conn: sqlite3.Connection,
    primary_id: str,
    duplicate_ids: list[str],
) -> int:
    """Rewrite duplicate entity_ids → primary in knowledge_units.

    Updates both the redundant ``entity_ids`` column and the
    ``payload.entities[].entity_id`` references. Returns count of KU rows touched.
    """
    refs_updated = 0
    for dup_id in duplicate_ids:
        # entity_ids column (JSON array)
        cursor = conn.execute(
            "SELECT ku_id, entity_ids FROM knowledge_units WHERE entity_ids LIKE ?",
            (f"%{dup_id}%",),
        )
        for ku_row in cursor.fetchall():
            ku_id = ku_row[0]
            entity_ids = json.loads(ku_row[1])
            if dup_id in entity_ids:
                entity_ids = [
                    primary_id if eid == dup_id else eid for eid in entity_ids
                ]
                conn.execute(
                    "UPDATE knowledge_units SET entity_ids = ? WHERE ku_id = ?",
                    (json.dumps(entity_ids, ensure_ascii=False), ku_id),
                )
                refs_updated += 1

        # payload.entities[].entity_id
        cursor = conn.execute(
            "SELECT ku_id, payload FROM knowledge_units WHERE payload LIKE ?",
            (f"%{dup_id}%",),
        )
        for ku_row in cursor.fetchall():
            ku_id = ku_row[0]
            payload = json.loads(ku_row[1])
            modified = False
            for entity_ref in payload.get("entities", []):
                if entity_ref.get("entity_id") == dup_id:
                    entity_ref["entity_id"] = primary_id
                    modified = True
            if modified:
                conn.execute(
                    "UPDATE knowledge_units SET payload = ? WHERE ku_id = ?",
                    (json.dumps(payload, ensure_ascii=False), ku_id),
                )

    return refs_updated


def _rewrite_cluster_references(
    conn: sqlite3.Connection,
    primary_id: str,
    duplicate_ids: list[str],
) -> None:
    """Rewrite duplicate entity_ids → primary in cluster_entity_map.

    If the primary is already in a cluster that the duplicate also references,
    delete the duplicate row (PRIMARY KEY would otherwise collide). Otherwise
    repoint the duplicate row to the primary.
    """
    for dup_id in duplicate_ids:
        dup_clusters = conn.execute(
            "SELECT cluster_id FROM cluster_entity_map WHERE entity_id = ?",
            (dup_id,),
        ).fetchall()
        for (cluster_id,) in dup_clusters:
            existing = conn.execute(
                "SELECT 1 FROM cluster_entity_map WHERE entity_id = ? AND cluster_id = ?",
                (primary_id, cluster_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "DELETE FROM cluster_entity_map WHERE entity_id = ? AND cluster_id = ?",
                    (dup_id, cluster_id),
                )
            else:
                conn.execute(
                    "UPDATE cluster_entity_map SET entity_id = ? "
                    "WHERE entity_id = ? AND cluster_id = ?",
                    (primary_id, dup_id, cluster_id),
                )


def _rebuild_primary_indexes(
    conn: sqlite3.Connection,
    primary_id: str,
    primary_norm: str,
    merged_aliases: list[str],
    merged_identifiers: dict[str, str],
) -> None:
    """Rebuild entity_aliases / entity_identifiers rows for the primary entity.

    Mirrors EntityRepository.save_batch: delete then re-insert, skipping aliases
    whose normalized form equals the canonical normalized_name, and normalizing
    each alias before insertion (dedup at the normalized level).
    """
    conn.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (primary_id,))
    conn.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (primary_id,))

    seen_norms: set[str] = set()
    alias_rows: list[tuple[str, str]] = []
    for alias in merged_aliases:
        norm_alias = normalize_entity_name(alias)
        if not norm_alias or norm_alias == primary_norm or norm_alias in seen_norms:
            continue
        seen_norms.add(norm_alias)
        alias_rows.append((primary_id, norm_alias))
    if alias_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO entity_aliases (entity_id, normalized_alias) VALUES (?, ?)",
            alias_rows,
        )

    ident_rows = [(primary_id, k, v) for k, v in merged_identifiers.items()]
    if ident_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO entity_identifiers "
            "(entity_id, identifier_key, identifier_value) VALUES (?, ?, ?)",
            ident_rows,
        )


def main():
    parser = argparse.ArgumentParser(description="Merge duplicate entities")
    parser.add_argument("--db", default="data/news.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview only (default: True)")
    parser.add_argument("--execute", dest="dry_run", action="store_false",
                        help="Actually execute the merge")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTING'}")
    print()

    stats = dedup_entities(args.db, dry_run=args.dry_run)

    print(f"Duplicate groups found: {stats['groups']}")
    print(f"Total duplicates to remove: {stats['total_duplicates_removed']}")
    print(f"Total references to update: {stats['total_references_updated']}")
    print()
    print("Details:")
    for d in stats["details"]:
        print(f"  [norm={d['normalized_name']!r}] type={d['entity_type']}")
        print(f"      canonicals merged: {d['canonical_names']}")
        print(f"      removed {d['duplicates_removed']} copies, "
              f"primary={d['primary_id']} ({d['primary_canonical']!r}), "
              f"merged KUs={d['merged_source_ku_count']}")

    if args.dry_run:
        print("\nRun with --execute to apply changes.")


if __name__ == "__main__":
    main()
