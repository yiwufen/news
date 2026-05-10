"""One-time migration: normalize unit_type values in existing knowledge_units.

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

    for row in rows:
        old_type = row["unit_type"]
        canonical = normalize_unit_type(old_type)
        new_type = canonical.value

        type_counts[new_type] = type_counts.get(new_type, 0) + 1

        if old_type != new_type:
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
    print("\nDistribution:")
    for ut, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = count / len(rows) * 100
        print(f"  {ut}: {count} ({pct:.1f}%)")

    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate unit_type to canonical values")
    parser.add_argument("--db", default="data/news.db", help="SQLite database path")
    args = parser.parse_args()
    updated = migrate(args.db)
    print(f"\nMigration complete: {updated} rows updated")


if __name__ == "__main__":
    main()
