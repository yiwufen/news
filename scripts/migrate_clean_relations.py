#!/usr/bin/env python3
"""Clean up legacy relation_hints in the database.

Removes relation_hints entries that:
  - Have relation_type outside the standard 20-type vocabulary
  - Have empty/null entity_ids (legacy architecture artifact)

Usage:
    # Dry run (preview only)
    uv run python scripts/migrate_clean_relations.py --dry-run

    # Execute
    uv run python scripts/migrate_clean_relations.py
"""

from __future__ import annotations

import json
import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

STANDARD_RELATION_TYPES: frozenset[str] = frozenset({
    "合作", "投资", "并购", "竞争", "供应", "监管", "处罚", "诉讼", "高管任职",
    "控股", "收购", "减持", "增持", "制裁", "袭击", "签署", "谴责", "威胁", "反对",
})


def clean_hints(hints: list[dict]) -> list[dict]:
    """Keep only hints with standard relation_type and valid entity references.

    Legacy data stores entity names / stock codes in entity_id fields.
    Only keep hints where at least one endpoint is a real entity_id (ent_xxx).
    """
    cleaned = []
    for h in hints:
        rt = h.get("relation_type", "")
        if rt not in STANDARD_RELATION_TYPES:
            continue
        subj_id = h.get("subject_entity_id") or ""
        obj_id = h.get("object_entity_id") or ""
        has_valid_subj = subj_id.startswith("ent_")
        has_valid_obj = obj_id.startswith("ent_")
        if not has_valid_subj and not has_valid_obj:
            continue
        cleaned.append(h)
    return cleaned


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    db_path = "data/news.db"

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT rowid, payload FROM knowledge_units").fetchall()

    total_ku = len(rows)
    updated = 0
    total_before = 0
    total_after = 0
    total_removed = 0

    updates: list[tuple[str, int]] = []  # (new_payload, rowid)

    for rowid, payload_str in rows:
        ku = json.loads(payload_str)
        hints = ku.get("relation_hints", [])
        if not hints:
            continue

        total_before += len(hints)
        cleaned = clean_hints(hints)
        total_after += len(cleaned)
        removed = len(hints) - len(cleaned)
        total_removed += removed

        if removed > 0:
            ku["relation_hints"] = cleaned
            updates.append((json.dumps(ku, ensure_ascii=False), rowid))
            updated += 1

    print(f"Database: {db_path}")
    print(f"Total KU: {total_ku}")
    print(f"Relation hints before: {total_before}")
    print(f"Relation hints after:  {total_after}")
    print(f"Removed: {total_removed} ({total_removed/total_before*100:.1f}%)")
    print(f"Affected KU: {updated}")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        # Show some samples of what would be kept
        kept_samples = 0
        for rowid, payload_str in rows:
            ku = json.loads(payload_str)
            hints = ku.get("relation_hints", [])
            cleaned = clean_hints(hints)
            if cleaned and kept_samples < 5:
                print(f"\n  Keep sample (ku_id={ku.get('ku_id', '?')}):")
                for h in cleaned:
                    print(f"    {h.get('relation_type')} | subj={h.get('subject_entity_id') or h.get('subject_mention')} obj={h.get('object_entity_id') or h.get('object_mention')}")
                kept_samples += 1
    else:
        conn.executemany(
            "UPDATE knowledge_units SET payload = ? WHERE rowid = ?",
            updates,
        )
        conn.commit()
        print(f"\nUpdated {updated} rows.")

    conn.close()


if __name__ == "__main__":
    main()
