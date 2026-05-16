"""Migrate vector index from LanceDB to FAISS.

One-time migration script.  Reads all vectors from the existing LanceDB
table, normalizes them, writes to a new FAISS IndexFlatIP + id_map.json,
then backs up the old LanceDB directory.

Usage:
    uv run python scripts/migrate_vectors.py [--db data/news.db]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import faiss
import numpy as np


def migrate(db_path: str = "data/news.db") -> None:
    vec_dir = Path(db_path).parent / "vector_db"
    lance_dir = vec_dir / "knowledge_units.lance"
    index_path = vec_dir / "faiss.index"
    id_map_path = vec_dir / "id_map.json"

    if not lance_dir.exists():
        print(f"No LanceDB data found at {lance_dir}")
        return

    if index_path.exists():
        print(f"FAISS index already exists at {index_path} — skipping migration")
        return

    # Import lancedb at migration time only (will be removed after migration)
    try:
        import lancedb  # pyright: ignore[reportMissingImports]
    except ImportError:
        print("ERROR: lancedb is not installed.  Install it with: uv add lancedb pyarrow")
        return

    db = lancedb.connect(str(vec_dir))
    table = db.open_table("knowledge_units")
    arrow_table = table.to_arrow()

    ku_ids: list[str] = arrow_table.column("ku_id").to_pylist()
    vectors: list[list[float]] = arrow_table.column("vector").to_pylist()
    n = len(ku_ids)
    print(f"Found {n} vectors in LanceDB")

    if n == 0:
        print("Nothing to migrate")
        return

    dim = len(vectors[0])
    arr = np.array(vectors, dtype=np.float32)
    faiss.normalize_L2(arr)

    flat = faiss.IndexFlatIP(dim)
    index = faiss.IndexIDMap(flat)
    ids = np.arange(n, dtype=np.int64)
    index.add_with_ids(arr, ids)  # type: ignore[call-arg]

    id_map = {str(i): ku_id for i, ku_id in enumerate(ku_ids)}

    # Write FAISS index
    vec_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    id_map_path.write_text(json.dumps(id_map, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote FAISS index ({n} vectors, dim={dim})")

    # Backup old LanceDB directory
    backup_dir = vec_dir.with_name("vector_db.lance.bak")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.move(str(vec_dir / "knowledge_units.lance"), str(backup_dir / "knowledge_units.lance"))
    print(f"Backed up LanceDB data to {backup_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate LanceDB → FAISS")
    parser.add_argument("--db", default="data/news.db", help="Path to SQLite DB")
    args = parser.parse_args()
    migrate(args.db)
