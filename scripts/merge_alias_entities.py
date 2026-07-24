"""Merge explicitly-reviewed entity pairs that share an alias relationship.

Background
----------
``dedup_entities.py`` only merges entities whose ``normalized_name`` is
identical (conservative, suffix-stripped exact match). That correctly refuses
to touch a much larger set of "looks like the same entity" pairs whose
canonical names differ even after normalization — e.g. ``港交所`` vs
``香港交易所``, ``特朗普`` vs ``唐纳德·特朗普``.

These pairs *should* be one entity, but they cannot be auto-detected safely:
the same surface pattern also matches ``小米`` vs ``小米健康`` (subsidiary),
``美国财政部`` vs ``英国财政部`` (same short name, different org),
``吉利控股集团`` vs ``吉利汽车`` (parent vs listed subsidiary). A name-pattern
classifier tried during diagnosis produced >20% false positives.

This script therefore operates on an **explicit, human-reviewed pair list**
(``MERGE_PAIRS``). Each pair was verified against identifiers / description /
source KU content. The list is intentionally small and append-only; do not
add pairs without that verification.

Merge semantics mirror ``dedup_entities.py``:
- primary = entity with most source_ku_ids (ties → shorter canonical_name);
- merge aliases / identifiers / source_ku_ids / tags into primary;
- rewrite ``knowledge_units.entity_ids`` + ``payload.entities[].entity_id``;
- rewrite ``cluster_entity_map`` (handling PK collision by deletion);
- delete duplicate + rebuild primary's alias/identifier index rows;
- all mutations inside a single ``BEGIN IMMEDIATE`` transaction.

Usage
-----
    # Preview (default): show what would happen, change nothing
    uv run python scripts/merge_alias_entities.py --db data/news.db

    # Apply
    uv run python scripts/merge_alias_entities.py --db data/news.db --execute

Pre-flight: back up the DB first, e.g.
    cp data/news.db data/news.db.bak.$(date +%Y%m%d_%H%M%S)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

from src.entities import normalize_entity_name

# Alias cap shared with EntityResolver / dedup_entities.py.
_MAX_ALIASES = 10

# Human-reviewed merge pairs. Each tuple is (canonical_a, canonical_b) — order
# does not imply which survives; primary is chosen by KU count at runtime.
#
# Inclusion criteria (all must hold):
#   1. The two canonical names are mutually referenced as aliases (A's
#      normalized canonical appears in B's alias set and vice versa), AND
#   2. entity_type is identical (or both empty), AND
#   3. Manual review of description + source KU content confirms same
#      real-world subject (not parent/subsidiary, not same-short-name
#      different org, not a "dirty" entity mixing multiple subjects).
#
# Excluded after review (documented for audit):
#   - 西矿集团 / 西部矿业        : parent (控股股东) vs listed co — keep separate
#   - 吉利控股集团 / 吉利汽车    : parent group vs HK-listed subsidiary — keep
#                                 separate
#   - 中国国防部 / 国防部         : "国防部" is a dirty entity mixing US/Saudi/
#                                 Kuwait/China/Germany/France MoD references;
#                                 needs splitting, not merging. Tracked in
#                                 docs/design-issues/entity-merge-followup.md.
MERGE_PAIRS: list[tuple[str, str]] = [
    ("五角大楼", "美国国防部"),
    ("特朗普", "唐纳德·特朗普"),
    ("工信部", "工业和信息化部"),
    ("SpaceX", "太空探索技术公司"),
    ("EIA", "美国能源信息署"),
    ("高瓴资本", "高瓴"),
    ("阿里巴巴", "阿里"),
    ("香港交易所", "港交所"),
    ("小米", "小米科技有限责任公司"),
    ("商务部", "中国商务部"),
    ("美国白宫", "白宫"),
    ("比亚迪", "比亚迪股份"),
    ("中通快递", "中通"),
    ("丽珠集团", "丽珠医药"),
]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_entities(
    conn: sqlite3.Connection,
) -> dict[str, dict]:
    """Return canonical_name → row dict for all entities."""
    rows = conn.execute(
        "SELECT entity_id, canonical_name, entity_type, normalized_name, "
        "payload FROM entities"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        out[r["canonical_name"]] = {
            "entity_id": r["entity_id"],
            "canonical_name": r["canonical_name"],
            "entity_type": r["entity_type"],
            "normalized_name": r["normalized_name"],
            "payload": json.loads(r["payload"]),
        }
    return out


def _pick_primary(a: dict, b: dict) -> tuple[dict, dict]:
    """Choose primary by most source_ku_ids, then shortest canonical_name."""
    a_ku = len(a["payload"].get("source_ku_ids", []))
    b_ku = len(b["payload"].get("source_ku_ids", []))
    if a_ku > b_ku:
        return a, b
    if b_ku > a_ku:
        return b, a
    if len(a["canonical_name"]) <= len(b["canonical_name"]):
        return a, b
    return b, a


def _rewrite_ku_references(
    conn: sqlite3.Connection,
    primary_id: str,
    dup_id: str,
) -> int:
    """Rewrite a single duplicate entity_id → primary in knowledge_units."""
    refs_updated = 0

    # entity_ids column (JSON array)
    cursor = conn.execute(
        "SELECT ku_id, entity_ids FROM knowledge_units WHERE entity_ids LIKE ?",
        (f"%{dup_id}%",),
    )
    for ku_row in cursor.fetchall():
        ku_id = ku_row["ku_id"]
        entity_ids = json.loads(ku_row["entity_ids"])
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
        ku_id = ku_row["ku_id"]
        payload = json.loads(ku_row["payload"])
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
    dup_id: str,
) -> None:
    """Rewrite duplicate entity_id → primary in cluster_entity_map."""
    dup_clusters = conn.execute(
        "SELECT cluster_id FROM cluster_entity_map WHERE entity_id = ?",
        (dup_id,),
    ).fetchall()
    for row in dup_clusters:
        cluster_id = row["cluster_id"]
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

    Mirrors EntityRepository.save_batch + dedup_entities._rebuild_primary_indexes.
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


def _merge_pair(
    conn: sqlite3.Connection,
    primary: dict,
    dup: dict,
    dry_run: bool,
) -> dict:
    """Merge ``dup`` into ``primary``. Returns a per-pair report dict."""
    primary_id = primary["entity_id"]
    dup_id = dup["entity_id"]
    primary_payload = dict(primary["payload"])
    dup_payload = dup["payload"]

    # Field merge (normalized-level dedup for aliases, same as dedup_entities).
    merged_aliases: list[str] = list(primary_payload.get("aliases", []))
    merged_identifiers: dict[str, str] = dict(primary_payload.get("identifiers", {}))
    merged_source_kus: list[str] = list(primary_payload.get("source_ku_ids", []))
    merged_tags: list[str] = list(primary_payload.get("tags", []))

    seen_alias_norms: set[str] = {
        normalize_entity_name(a) for a in merged_aliases if a
    }
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

    report = {
        "primary": {
            "entity_id": primary_id,
            "canonical_name": primary["canonical_name"],
            "type": primary["entity_type"],
            "ku_before": len(primary_payload.get("source_ku_ids", [])),
            "ku_after": len(merged_source_kus),
        },
        "duplicate": {
            "entity_id": dup_id,
            "canonical_name": dup["canonical_name"],
            "type": dup["entity_type"],
            "ku": len(dup_payload.get("source_ku_ids", [])),
        },
        "merged_aliases_added": len(merged_aliases) - len(primary_payload.get("aliases", [])),
        "merged_identifiers": dict(merged_identifiers),
        "refs_updated": 0,
    }

    if not dry_run:
        now_iso = _utcnow_iso()
        primary_payload["aliases"] = merged_aliases
        primary_payload["identifiers"] = merged_identifiers
        primary_payload["source_ku_ids"] = merged_source_kus
        primary_payload["tags"] = merged_tags
        primary_payload["updated_at"] = now_iso

        primary_norm = primary["normalized_name"] or normalize_entity_name(
            primary["canonical_name"]
        )
        primary_identifier_value = next(iter(merged_identifiers.values()), None)
        primary_payload_json = json.dumps(primary_payload, ensure_ascii=False)

        conn.execute(
            """
            UPDATE entities
            SET canonical_name = ?,
                entity_type = ?,
                primary_identifier = ?,
                normalized_name = ?,
                payload = ?,
                updated_at = ?
            WHERE entity_id = ?
            """,
            (
                primary["canonical_name"], primary["entity_type"] or "",
                primary_identifier_value, primary_norm,
                primary_payload_json, now_iso, primary_id,
            ),
        )

        report["refs_updated"] = _rewrite_ku_references(conn, primary_id, dup_id)
        _rewrite_cluster_references(conn, primary_id, dup_id)

        conn.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (dup_id,))
        conn.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (dup_id,))
        conn.execute("DELETE FROM entities WHERE entity_id = ?", (dup_id,))

        _rebuild_primary_indexes(
            conn, primary_id, primary_norm, merged_aliases, merged_identifiers
        )

    return report


def merge_alias_entities(db_path: str, dry_run: bool = True) -> dict:
    """Apply the reviewed MERGE_PAIRS to ``db_path``. Returns a summary."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    by_canonical = _load_entities(conn)

    # Validate every pair resolves to exactly two distinct entities.
    errors: list[str] = []
    plans: list[tuple[dict, dict]] = []
    for name_a, name_b in MERGE_PAIRS:
        if name_a not in by_canonical:
            errors.append(f"entity not found: {name_a!r}")
            continue
        if name_b not in by_canonical:
            errors.append(f"entity not found: {name_b!r}")
            continue
        a = by_canonical[name_a]
        b = by_canonical[name_b]
        if a["entity_id"] == b["entity_id"]:
            errors.append(f"{name_a!r} and {name_b!r} are already the same entity")
            continue
        plans.append((a, b))

    if errors:
        conn.close()
        return {"errors": errors, "reports": []}

    if not dry_run:
        conn.execute("BEGIN IMMEDIATE")

    reports: list[dict] = []
    try:
        for a, b in plans:
            primary, dup = _pick_primary(a, b)
            reports.append(_merge_pair(conn, primary, dup, dry_run))
    except Exception:
        if not dry_run:
            conn.rollback()
        conn.close()
        raise

    if not dry_run:
        conn.commit()
    conn.close()

    return {"errors": [], "reports": reports}


def _print_report(summary: dict, dry_run: bool) -> int:
    errors = summary.get("errors", [])
    if errors:
        print("Pre-flight errors (no changes made):")
        for e in errors:
            print(f"  - {e}")
        return 1

    reports = summary["reports"]
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTED'}")
    print(f"Pairs processed: {len(reports)}")
    print()
    total_refs = 0
    for r in reports:
        p, d = r["primary"], r["duplicate"]
        total_refs += r["refs_updated"]
        print(
            f"  [{p['type'] or '-':12s}] "
            f"{p['canonical_name']!r} (KU {p['ku_before']}→{p['ku_after']})  "
            f"<<  {d['canonical_name']!r} (KU {d['ku']})"
        )
        if r["merged_aliases_added"]:
            print(f"      +{r['merged_aliases_added']} aliases merged")
    print()
    print(f"Total KU references rewritten: {total_refs}")
    if dry_run:
        print("\nRun with --execute to apply.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge human-reviewed alias-collision entity pairs"
    )
    parser.add_argument("--db", default="data/news.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview only (default)")
    parser.add_argument("--execute", dest="dry_run", action="store_false",
                        help="Apply the merges")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    if not args.dry_run:
        print("WARNING: this will mutate the database. Ensure you have a backup.")
    print()

    summary = merge_alias_entities(args.db, dry_run=args.dry_run)
    return _print_report(summary, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
