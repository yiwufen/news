"""Manage a frozen DB snapshot for reproducible retrieval evaluation.

The running ``data/news.db`` is mutated continuously by the crawler. To make
eval scores comparable across runs, we copy it once into
``docs/eval/eval_snapshot.db`` and record provenance metadata (source mtime,
KU count, git commit, copy timestamp). All eval runs MUST point at this
snapshot.

Usage::

    uv run python docs/eval/scripts/snapshot.py           # create / refresh
    uv run python docs/eval/scripts/snapshot.py --status  # show current snapshot
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DB = REPO_ROOT / "data" / "news.db"
SNAPSHOT_DB = REPO_ROOT / "docs" / "eval" / "eval_snapshot.db"
META_FILE = REPO_ROOT / "docs" / "eval" / "snapshot_meta.json"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _git_dirty() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
        return bool(out)
    except Exception:
        return False


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_kus(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def create_snapshot(force: bool = False) -> dict:
    """Copy source DB into the snapshot path and write provenance metadata."""
    if not SOURCE_DB.exists():
        raise FileNotFoundError(
            f"Source DB not found: {SOURCE_DB}. Run the pipeline first to populate data/news.db."
        )
    if SNAPSHOT_DB.exists() and not force:
        print(f"Snapshot already exists: {SNAPSHOT_DB}")
        print("Use --force to overwrite.")
        return load_meta() or {}

    SNAPSHOT_DB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_DB, SNAPSHOT_DB)

    meta = {
        "source_db": str(SOURCE_DB.relative_to(REPO_ROOT)),
        "source_mtime": datetime.fromtimestamp(
            SOURCE_DB.stat().st_mtime, UTC
        ).isoformat(),
        "snapshot_path": str(SNAPSHOT_DB.relative_to(REPO_ROOT)),
        "snapshot_created": datetime.now(UTC).isoformat(),
        "source_sha256": _file_sha256(SOURCE_DB),
        "ku_count": _count_kus(SNAPSHOT_DB),
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
    }
    META_FILE.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Snapshot created: {SNAPSHOT_DB}")
    print(f"  KU count:     {meta['ku_count']}")
    print(f"  source sha256: {meta['source_sha256'][:16]}...")
    print(f"  git commit:   {meta['git_commit'][:12]}{' (dirty)' if meta['git_dirty'] else ''}")
    return meta


def load_meta() -> dict | None:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    return None


def show_status() -> None:
    meta = load_meta()
    if not meta:
        print("No snapshot metadata. Run without --status to create one.")
        return
    if not SNAPSHOT_DB.exists():
        print(f"WARNING: metadata exists but snapshot file is missing: {SNAPSHOT_DB}")
        return

    current_sha = _file_sha256(SNAPSHOT_DB)
    sha_matches = current_sha == meta.get("snapshot_sha256", "")
    # snapshot_sha256 is not persisted at creation (source sha is). Compute now.
    print("Current eval snapshot:")
    print(f"  path:        {meta['snapshot_path']}")
    print(f"  created:     {meta['snapshot_created']}")
    print(f"  source db:   {meta['source_db']} (mtime {meta['source_mtime']})")
    print(f"  KU count:    {meta['ku_count']}")
    print(f"  git commit:  {meta['git_commit']}{' (dirty)' if meta['git_dirty'] else ''}")
    print(f"  source sha:  {meta['source_sha256'][:16]}...")
    print(f"  snapshot sha: {current_sha[:16]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing snapshot"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show current snapshot metadata"
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return
    create_snapshot(force=args.force)


if __name__ == "__main__":
    main()
