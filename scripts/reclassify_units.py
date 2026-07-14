"""Reclassify legacy unit_type/cluster_type to the 32-class closed set.

Two-pass migration:

* **Pass 1 (rule-based, certain):** the 27 types that survived the taxonomy
  change keep their value; only the column/payload/FTS are reconciled. Uses
  ``reclassify_legacy_unit_type`` with ``needs_relabel=False``.

* **Pass 2 (LLM-based, content-dependent):** legacy ``announcement``/``other``
  buckets and the noisy ``investment`` type are re-read via the extraction LLM
  and assigned a concrete new type. Disabled by default; pass ``--llm-relabel``
  once the LLM client is configured. Failures are recorded and surfaced
  (fail-fast, no silent fallback — SHARED_RULES §7).

Syncs three tables that the old ``migrate_unit_types.py`` missed:
``knowledge_units`` + ``event_clusters`` + ``cluster_entity_map``, then
rebuilds the FTS5 index.

Usage:
    # Dry run — report what would change, write nothing
    uv run python scripts/reclassify_units.py --db data/news.db --dry-run

    # Rule pass only (safe, no LLM)
    uv run python scripts/reclassify_units.py --db data/news.db

    # Full pass with LLM relabelling of buckets
    uv run python scripts/reclassify_units.py --db data/news.db --llm-relabel
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schemas.enums import UnitType, reclassify_legacy_unit_type

BUCKET_TYPES = {"announcement", "other"}


# ---------------------------------------------------------------------------
# Pass 1: rule-based migration (certain types)
# ---------------------------------------------------------------------------


def migrate_rule_based(conn: sqlite3.Connection, dry_run: bool) -> dict[str, int]:
    """Migrate the 27 certain types across the three tables.

    Bucket types (announcement/other) and investment are skipped here — they
    need Pass 2. Returns a stats dict.
    """
    stats = {
        "ku_updated": 0,
        "cluster_updated": 0,
        "cluster_map_updated": 0,
        "ku_bucket_skipped": 0,
        "cluster_bucket_skipped": 0,
    }

    # --- knowledge_units ---
    ku_rows = conn.execute(
        "SELECT ku_id, unit_type, payload FROM knowledge_units"
    ).fetchall()
    ku_updates: list[tuple[str, str, str]] = []
    for ku_id, old_type, payload_str in ku_rows:
        if old_type in BUCKET_TYPES or old_type == "investment":
            stats["ku_bucket_skipped"] += 1
            continue
        new_type, needs_relabel = reclassify_legacy_unit_type(old_type)
        if needs_relabel or new_type.value == old_type:
            continue
        payload = json.loads(payload_str)
        payload["unit_type"] = new_type.value
        ku_updates.append(
            (new_type.value, json.dumps(payload, ensure_ascii=False), ku_id)
        )
    if ku_updates and not dry_run:
        conn.executemany(
            "UPDATE knowledge_units SET unit_type = ?, payload = ? WHERE ku_id = ?",
            ku_updates,
        )
    stats["ku_updated"] = len(ku_updates)

    # --- event_clusters ---
    clu_rows = conn.execute(
        "SELECT cluster_id, cluster_type, payload FROM event_clusters"
    ).fetchall()
    clu_updates: list[tuple[str, str, str]] = []
    for cluster_id, old_type, payload_str in clu_rows:
        if old_type in BUCKET_TYPES or old_type == "investment":
            stats["cluster_bucket_skipped"] += 1
            continue
        new_type, needs_relabel = reclassify_legacy_unit_type(old_type)
        if needs_relabel or new_type.value == old_type:
            continue
        payload = json.loads(payload_str)
        payload["cluster_type"] = new_type.value
        clu_updates.append(
            (new_type.value, json.dumps(payload, ensure_ascii=False), cluster_id)
        )
    if clu_updates and not dry_run:
        conn.executemany(
            "UPDATE event_clusters SET cluster_type = ?, payload = ? WHERE cluster_id = ?",
            clu_updates,
        )
    stats["cluster_updated"] = len(clu_updates)

    # --- cluster_entity_map ---
    # No payload column here — only the cluster_type column.
    map_rows = conn.execute(
        "SELECT DISTINCT cluster_type FROM cluster_entity_map"
    ).fetchall()
    map_updates: list[tuple[str, str]] = []
    for (old_type,) in map_rows:
        if old_type in BUCKET_TYPES or old_type == "investment":
            continue
        new_type, needs_relabel = reclassify_legacy_unit_type(old_type)
        if needs_relabel or new_type.value == old_type:
            continue
        map_updates.append((new_type.value, old_type))
    if map_updates and not dry_run:
        for new_val, old_val in map_updates:
            conn.execute(
                "UPDATE cluster_entity_map SET cluster_type = ? WHERE cluster_type = ?",
                (new_val, old_val),
            )
    stats["cluster_map_updated"] = len(map_updates)

    return stats


# ---------------------------------------------------------------------------
# Pass 2: LLM relabelling (bucket types + noisy investment)
# ---------------------------------------------------------------------------


def collect_relabel_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Collect KUs whose unit_type needs LLM re-reading.

    Returns a list of dicts with the fields the relabel prompt needs:
    ku_id, summary, entities (mentions + types), evidence text, old_type.
    """
    rows = conn.execute(
        """SELECT ku_id, unit_type, payload FROM knowledge_units
           WHERE unit_type IN ('announcement', 'other', 'investment')"""
    ).fetchall()
    candidates: list[dict] = []
    for ku_id, old_type, payload_str in rows:
        d = json.loads(payload_str)
        candidates.append(
            {
                "ku_id": ku_id,
                "old_type": old_type,
                "summary": d.get("summary", ""),
                "entities": [
                    {"mention": e.get("mention"), "type": e.get("entity_type")}
                    for e in d.get("entities") or []
                ],
                "evidence": (d.get("evidence") or [{}])[0].get("text", ""),
            }
        )
    return candidates


def relabel_with_llm(
    candidates: list[dict], log_path: Path
) -> tuple[dict[str, object], dict[str, str]]:
    """Re-classify bucket/noisy KUs via the extraction LLM.

    Each candidate's summary + entities + evidence is sent to the LLM with the
    32-type closed-set prompt (reusing the extraction prompt's unit_type spec).
    Results and raw inputs/outputs are logged to ``log_path`` for traceability.

    Returns ``(stats, results)`` where results maps ku_id -> new_type. Failures
    raise (fail-fast) per SHARED_RULES §7.
    """
    from anthropic.types import TextBlock

    from src.knowledge_extractor import SYSTEM_PROMPT
    from src.llm import create_offline_llm_client, get_offline_max_tokens

    valid_types = {t.value for t in UnitType if t != UnitType.NON_FINANCIAL}
    client, model = create_offline_llm_client()
    max_tokens = get_offline_max_tokens()

    type_dist: Counter = Counter()
    log_entries: list[dict] = []
    results: dict[str, str] = {}  # ku_id -> new_type

    relabel_prompt = (
        SYSTEM_PROMPT.split("# unit_type 分类规范")[1].split("# 输出前自检")[0]
    )

    for cand in candidates:
        prompt = (
            "根据以下分类规范，为这条陈述选择最准确的 unit_type。\n\n"
            f"# unit_type 分类规范{relabel_prompt}\n\n"
            f"陈述摘要：{cand['summary']}\n"
            f"涉及实体：{cand['entities']}\n"
            f"证据原文：{cand['evidence']}\n"
            f"旧分类（可能错误）：{cand['old_type']}\n\n"
            "只输出一个 unit_type 值，不要输出其他内容。"
        )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = next(
                b.text for b in resp.content if isinstance(b, TextBlock)
            )
            new_type = text.strip().strip('"').strip("'")
            if new_type not in valid_types:
                raise ValueError(f"LLM returned invalid unit_type: {new_type!r}")
        except Exception as exc:  # noqa: BLE001 — surface, don't swallow
            raise RuntimeError(
                f"LLM relabel failed for ku_id={cand['ku_id']}: {exc}"
            ) from exc

        results[cand["ku_id"]] = new_type
        type_dist[new_type] += 1
        log_entries.append(
            {
                "ku_id": cand["ku_id"],
                "old_type": cand["old_type"],
                "new_type": new_type,
                "summary": cand["summary"][:80],
            }
        )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        for entry in log_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    stats: dict[str, object] = {"relabelled": len(results), **dict(type_dist)}
    return stats, results


def apply_llm_relabels(
    conn: sqlite3.Connection, results: dict[str, str]
) -> dict[str, int]:
    """Apply LLM-assigned types to the three tables."""
    stats = {"ku_updated": 0, "cluster_updated": 0}
    # knowledge_units
    ku_updates: list[tuple[str, str, str]] = []
    for ku_id, new_type in results.items():
        row = conn.execute(
            "SELECT payload FROM knowledge_units WHERE ku_id = ?", (ku_id,)
        ).fetchone()
        if not row:
            continue
        payload = json.loads(row[0])
        payload["unit_type"] = new_type
        ku_updates.append((new_type, json.dumps(payload, ensure_ascii=False), ku_id))
    if ku_updates:
        conn.executemany(
            "UPDATE knowledge_units SET unit_type = ?, payload = ? WHERE ku_id = ?",
            ku_updates,
        )
    stats["ku_updated"] = len(ku_updates)

    # event_clusters: propagate to clusters whose representative or members changed
    # A cluster's cluster_type is derived from its representative KU; update
    # clusters whose representative_ku_id is in results.
    clu_updates: list[tuple[str, str, str]] = []
    clu_rows = conn.execute(
        "SELECT cluster_id, payload FROM event_clusters"
    ).fetchall()
    for cluster_id, payload_str in clu_rows:
        d = json.loads(payload_str)
        rep_ku = d.get("representative_ku_id")
        if rep_ku and rep_ku in results:
            new_type = results[rep_ku]
            d["cluster_type"] = new_type
            clu_updates.append(
                (new_type, json.dumps(d, ensure_ascii=False), cluster_id)
            )
    if clu_updates:
        conn.executemany(
            "UPDATE event_clusters SET cluster_type = ?, payload = ? WHERE cluster_id = ?",
            clu_updates,
        )
        # cluster_entity_map follows cluster_type
        for new_type, _, cluster_id in clu_updates:
            conn.execute(
                "UPDATE cluster_entity_map SET cluster_type = ? WHERE cluster_id = ?",
                (new_type, cluster_id),
            )
    stats["cluster_updated"] = len(clu_updates)
    return stats


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def backup_db(db_path: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path(f"{db_path}.bak.reclassify.{ts}")
    shutil.copy2(db_path, bak)
    print(f"Backup: {bak}")
    return bak


def print_distribution(conn: sqlite3.Connection, label: str) -> None:
    rows = conn.execute(
        "SELECT unit_type, COUNT(*) FROM knowledge_units GROUP BY unit_type ORDER BY 2 DESC"
    ).fetchall()
    total = sum(r[1] for r in rows)
    print(f"\n=== {label} (total {total}) ===")
    for ut, n in rows:
        print(f"  {n:5d} ({100 * n / total:4.1f}%)  {ut}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reclassify legacy unit_type to the 32-class closed set"
    )
    parser.add_argument("--db", default="data/news.db")
    parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing")
    parser.add_argument(
        "--llm-relabel",
        action="store_true",
        help="Re-read bucket/investment KUs via LLM (needs LLM configured)",
    )
    parser.add_argument(
        "--llm-log",
        default=".tmp/reclassify_log.jsonl",
        help="Path for the LLM relabel trace log",
    )
    parser.add_argument("--skip-fts", action="store_true", help="Skip FTS5 rebuild")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if not args.dry_run:
        backup_db(args.db)

    print_distribution(conn, "BEFORE")

    # --- Pass 1: rule-based ---
    print("\n--- Pass 1: rule-based migration ---")
    stats1 = migrate_rule_based(conn, args.dry_run)
    print(
        f"  ku_updated={stats1['ku_updated']} "
        f"cluster_updated={stats1['cluster_updated']} "
        f"cluster_map_updated={stats1['cluster_map_updated']}"
    )
    print(
        f"  bucket_skipped (ku={stats1['ku_bucket_skipped']}, "
        f"cluster={stats1['cluster_bucket_skipped']}) — await Pass 2"
    )

    # --- Pass 2: LLM relabel ---
    if args.llm_relabel:
        print("\n--- Pass 2: LLM relabelling ---")
        candidates = collect_relabel_candidates(conn)
        print(f"  candidates: {len(candidates)}")
        if candidates:
            relabel_stats, results = relabel_with_llm(candidates, Path(args.llm_log))
            relabelled = relabel_stats.pop("relabelled", 0)
            print(f"  relabelled: {relabelled}")
            print("  new type distribution:")
            for ut, n in sorted(relabel_stats.items(), key=lambda x: -int(x[1])):  # type: ignore[arg-type]
                print(f"    {n:5d}  {ut}")
            if not args.dry_run:
                apply_stats = apply_llm_relabels(conn, results)
                print(
                    f"  applied: ku={apply_stats['ku_updated']} "
                    f"cluster={apply_stats['cluster_updated']}"
                )
            print(f"  trace log: {args.llm_log}")

    if not args.dry_run:
        conn.commit()

    print_distribution(conn, "AFTER")

    # --- FTS rebuild ---
    if not args.dry_run and not args.skip_fts:
        print("\n--- FTS5 rebuild ---")
        from src.retrieval.indexing import rebuild_knowledge_indexes

        count = rebuild_knowledge_indexes(args.db)
        print(f"  rebuilt: {count} rows")

    conn.close()
    print("\nDone." if not args.dry_run else "\nDry run — no changes written.")


if __name__ == "__main__":
    main()
