"""Merge duplicate entities with the same canonical_name.

Usage:
    uv run python scripts/dedup_entities.py --db data/news.db [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict


def dedup_entities(db_path: str, dry_run: bool = True) -> dict:
    """Merge duplicate entities and return summary stats."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    # Find duplicate groups
    dup_groups = conn.execute("""
        SELECT canonical_name, COUNT(*) as cnt, entity_type
        FROM entities
        GROUP BY canonical_name
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    stats = {
        "groups": len(dup_groups),
        "total_duplicates_removed": 0,
        "total_references_updated": 0,
        "details": [],
    }

    for canonical_name, count, entity_type in dup_groups:
        # Get all entities in this group, ordered by source_ku_ids count (desc)
        rows = conn.execute("""
            SELECT entity_id, payload FROM entities
            WHERE canonical_name = ?
            ORDER BY json_array_length(json_extract(payload, '$.source_ku_ids')) DESC, updated_at DESC
        """, (canonical_name,)).fetchall()

        if len(rows) < 2:
            continue

        # First entity is the primary (most source KUs)
        primary_id = rows[0][0]
        primary_payload = json.loads(rows[0][1])
        duplicate_ids = [r[0] for r in rows[1:]]

        # Build map of entity_id → payload for duplicates
        dup_payloads = {r[0]: json.loads(r[1]) for r in rows[1:]}

        # Merge aliases, identifiers, source_ku_ids from duplicates into primary
        merged_aliases: list[str] = list(primary_payload.get("aliases", []))
        merged_identifiers: dict[str, str] = dict(primary_payload.get("identifiers", {}))
        merged_source_kus: list[str] = list(primary_payload.get("source_ku_ids", []))
        seen_aliases: set[str] = set(merged_aliases)

        for dup_id in duplicate_ids:
            dup_payload = dup_payloads[dup_id]
            # Merge aliases
            for alias in dup_payload.get("aliases", []):
                if alias not in seen_aliases:
                    merged_aliases.append(alias)
                    seen_aliases.add(alias)
            # Merge identifiers
            for k, v in dup_payload.get("identifiers", {}).items():
                if k not in merged_identifiers:
                    merged_identifiers[k] = v
            # Merge source KU IDs
            for ku_id in dup_payload.get("source_ku_ids", []):
                if ku_id not in merged_source_kus:
                    merged_source_kus.append(ku_id)

        if not dry_run:
            # Update primary entity
            primary_payload["aliases"] = merged_aliases
            primary_payload["identifiers"] = merged_identifiers
            primary_payload["source_ku_ids"] = merged_source_kus

            conn.execute("""
                UPDATE entities
                SET payload = ?, updated_at = datetime('now')
                WHERE entity_id = ?
            """, (json.dumps(primary_payload, ensure_ascii=False), primary_id))

            # Update knowledge_units: replace duplicate entity_ids in entity_ids JSON array
            refs_updated = 0
            for dup_id in duplicate_ids:
                # Update entity_ids column in knowledge_units
                cursor = conn.execute("""
                    SELECT ku_id, entity_ids FROM knowledge_units
                    WHERE entity_ids LIKE ?
                """, (f"%{dup_id}%",))
                for ku_row in cursor.fetchall():
                    ku_id = ku_row[0]
                    entity_ids = json.loads(ku_row[1])
                    if dup_id in entity_ids:
                        entity_ids = [
                            primary_id if eid == dup_id else eid
                            for eid in entity_ids
                        ]
                        conn.execute(
                            "UPDATE knowledge_units SET entity_ids = ? WHERE ku_id = ?",
                            (json.dumps(entity_ids, ensure_ascii=False), ku_id),
                        )
                        refs_updated += 1

                # Update entity_ids in knowledge_units payload
                cursor = conn.execute("""
                    SELECT ku_id, payload FROM knowledge_units
                    WHERE payload LIKE ?
                """, (f"%{dup_id}%",))
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

                # Update cluster_entity_map: handle UNIQUE constraint
                # If primary already in cluster, delete dup row; otherwise update
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
                        # Primary already in this cluster — just delete dup
                        conn.execute(
                            "DELETE FROM cluster_entity_map WHERE entity_id = ? AND cluster_id = ?",
                            (dup_id, cluster_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE cluster_entity_map SET entity_id = ? WHERE entity_id = ? AND cluster_id = ?",
                            (primary_id, dup_id, cluster_id),
                        )

                # Delete entity_aliases for duplicate
                conn.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (dup_id,))

                # Delete entity_identifiers for duplicate
                conn.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (dup_id,))

                # Delete the duplicate entity
                conn.execute("DELETE FROM entities WHERE entity_id = ?", (dup_id,))

            stats["total_duplicates_removed"] += len(duplicate_ids)
            stats["total_references_updated"] += refs_updated

        stats["details"].append({
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "duplicates_removed": len(duplicate_ids),
            "primary_id": primary_id,
            "merged_source_ku_count": len(merged_source_kus),
        })

    if not dry_run:
        conn.commit()
    conn.close()
    return stats


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
        print(f"  {d['canonical_name']} ({d['entity_type']}): "
              f"removed {d['duplicates_removed']} copies, "
              f"primary={d['primary_id']}, "
              f"merged KUs={d['merged_source_ku_count']}")

    if args.dry_run:
        print("\nRun with --execute to apply changes.")


if __name__ == "__main__":
    main()
