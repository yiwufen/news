"""One-time migration: normalize unit_type values in existing knowledge_units.

Also rebuilds the FTS5 index so that normalized unit_type values are searchable.

Usage:
    uv run python scripts/migrate_unit_types.py [--db data/news.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schemas.enums import UnitType, normalize_unit_type


def migrate(db_path: str = "data/news.db") -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ku_id, unit_type, payload FROM knowledge_units"
    ).fetchall()

    updates: list[tuple[str, str, str]] = []
    type_counts: dict[str, int] = {}
    mappings: list[tuple[str, str, int]] = []  # (old, new, count)
    change_counts: dict[str, dict[str, int]] = {}  # old -> {new -> count}

    for row in rows:
        old_type = row["unit_type"]
        canonical = normalize_unit_type(old_type)
        new_type = canonical.value

        type_counts[new_type] = type_counts.get(new_type, 0) + 1

        if old_type != new_type:
            change_counts.setdefault(old_type, {})
            change_counts[old_type][new_type] = change_counts[old_type].get(new_type, 0) + 1
            payload = json.loads(row["payload"])
            payload["unit_type"] = new_type
            updates.append(
                (new_type, json.dumps(payload, ensure_ascii=False), row["ku_id"])
            )

    if updates:
        conn.executemany(
            "UPDATE knowledge_units SET unit_type = ?, payload = ? WHERE ku_id = ?",
            updates,
        )
        conn.commit()

    conn.close()

    print(f"Total KUs: {len(rows)}")
    print(f"Updated: {len(updates)}")
    print(f"Unique types after migration: {len(type_counts)}")

    if change_counts:
        print(f"\n=== {len(change_counts)} values remapped ===")
        for old, targets in sorted(change_counts.items(), key=lambda x: -sum(x[1].values())):
            for new, cnt in targets.items():
                print(f"  {old} -> {new} ({cnt} rows)")

    print("\nDistribution after migration:")
    for ut, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = count / len(rows) * 100
        print(f"  {ut}: {count} ({pct:.1f}%)")

    return len(updates)


def rebuild_fts(db_path: str = "data/news.db") -> int:
    """Rebuild the FTS5 index from all persisted KnowledgeUnit rows."""
    from src.retrieval.indexing import rebuild_knowledge_indexes

    count = rebuild_knowledge_indexes(db_path)
    print(f"FTS5 index rebuilt: {count} rows")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate unit_type to canonical values")
    parser.add_argument("--db", default="data/news.db", help="SQLite database path")
    parser.add_argument("--skip-fts", action="store_true", help="Skip FTS5 rebuild")
    args = parser.parse_args()

    updated = migrate(args.db)
    print(f"\nMigration complete: {updated} rows updated")

    if not args.skip_fts:
        rebuild_fts(args.db)


if __name__ == "__main__":
    main()
