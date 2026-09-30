"""One-time prune of pure-state (quote-snapshot) knowledge units.

Background
----------
生产库约 18.9%（23,179 条）KU 是"某股/板块涨跌多少"类状态描述：71% 无任何
因果归因、半衰期以小时计，却永久占据 FTS、向量索引、事件簇与图谱，并与
marketdata 行情工具完全重复。``src.pipeline.state_filter.is_pure_state_unit``
已在管道准入侧拦截新增泄漏；本脚本清理存量（用完即弃）。规格见
``docs/design-issues/state-vs-statement-routing.md`` §2.3。

选择规则与管道准入同一实现（``is_pure_state_unit``），边界不漂移：凡
unit_type ∈ 行情三类型 ∧ 行情形态 ∧ 无归因词 ∧ 无事件实质词 的 KU 全部删除。

Usage
-----
    # 预览：只出报告，不写库（缺省 dry-run）
    uv run python scripts/prune_state_kus.py --db data/news.db --sample 15

    # 执行（仅 SQLite）
    uv run python scripts/prune_state_kus.py --db data/news.db --execute

    # 执行 + 同步删除 Neo4j 中被清空的 EventCluster 节点
    uv run python scripts/prune_state_kus.py --db data/news.db --execute --with-graph

Steps (--execute):
    1. 删 knowledge_units 与 knowledge_units_fts 对应行（两表同删，防 FTS
       触发全量重建）——单事务；
    2. 删 member_ku_ids 全部命中删除集的 event_clusters 簇行及
       cluster_entity_map 行（同一事务）；
    3. (--with-graph) KnowledgeGraphSync.delete_node(cluster_id) 删图上
       对应 EventCluster 节点（实体节点一律不删）；
    4. 打印 source_ku_ids 全部被删的实体只读报告（人工定夺，不删实体）。

Pre-flight: 先跑 ``scripts/backup.sh``（SQLite）；--with-graph 时另行
``neo4j-admin database dump``。

Post-flight: 重建向量索引（FAISS + id_map.json，产物布局同
``scripts/migrate_vectors.py``）、用 ``scripts/snapshot_eval_pair.py``
重生成 eval fixture，并跑 ``eval_run.py`` / ``eval_guard.py``。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import cast

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge_base import KnowledgeUnit
from src.pipeline.state_filter import STATE_UNIT_TYPES, is_pure_state_unit


class PrunePlan:
    """扫描结果（dry-run 报告与 --execute 共用）。"""

    def __init__(self) -> None:
        self.total_kus: int = 0
        self.quote_kus: int = 0  # unit_type ∈ 行情三类型的 KU 数
        self.drop_ids: set[str] = set()
        self.drop_samples: list[tuple[str, str, str]] = []  # (ku_id, unit_type, summary)
        self.empty_cluster_ids: list[str] = []
        self.orphan_entities: list[tuple[str, str, int]] = []  # (entity_id, name, ku 数)


def build_plan(conn: sqlite3.Connection, sample_n: int) -> PrunePlan:
    """全量扫描并构造删除计划；不写任何数据。"""
    plan = PrunePlan()
    plan.total_kus = int(conn.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0])

    # 预筛 unit_type 只是性能优化（行情三类型仅 ~19%）；最终判定一律走
    # is_pure_state_unit，与管道准入同一实现，边界不漂移。
    placeholders = ", ".join("?" for _ in STATE_UNIT_TYPES)
    rows = conn.execute(
        f"SELECT ku_id, unit_type, payload FROM knowledge_units WHERE unit_type IN ({placeholders})",
        sorted(STATE_UNIT_TYPES),
    ).fetchall()
    plan.quote_kus = len(rows)
    for row in rows:
        unit = KnowledgeUnit.model_validate(json.loads(row["payload"]))
        if is_pure_state_unit(unit):
            plan.drop_ids.add(unit.ku_id)
            if len(plan.drop_samples) < sample_n:
                plan.drop_samples.append((unit.ku_id, unit.unit_type, unit.summary))

    # 簇：member_ku_ids 全部命中删除集 → 删除后将成为空簇，直接删行。
    # 成员列表为空的簇是历史坏数据，不在本脚本职责内，保守不动。
    for row in conn.execute("SELECT cluster_id, payload FROM event_clusters").fetchall():
        payload = cast(dict[str, object], json.loads(row["payload"]))
        member_ids = cast(list[str], payload.get("member_ku_ids") or [])
        if member_ids and plan.drop_ids.issuperset(set(member_ids)):
            plan.empty_cluster_ids.append(str(row["cluster_id"]))

    # 实体：source_ku_ids 全部被删 → 只读报告（是否清理由人工定夺）
    for row in conn.execute("SELECT payload FROM entities").fetchall():
        payload = cast(dict[str, object], json.loads(row["payload"]))
        source_ku_ids = cast(list[str], payload.get("source_ku_ids") or [])
        if source_ku_ids and plan.drop_ids.issuperset(set(source_ku_ids)):
            plan.orphan_entities.append(
                (str(payload.get("entity_id")), str(payload.get("canonical_name")), len(source_ku_ids))
            )
    return plan


def report(plan: PrunePlan, sample_n: int, mode: str) -> None:
    print(f"Mode: {mode}")
    print(f"Total KUs: {plan.total_kus}")
    print(f"Quote-type KUs (3 types): {plan.quote_kus}")
    drop_pct = len(plan.drop_ids) / plan.quote_kus * 100 if plan.quote_kus else 0.0
    print(f"KUs to delete: {len(plan.drop_ids)} ({drop_pct:.1f}% of quote-type)")
    print(f"Empty clusters to delete: {len(plan.empty_cluster_ids)}")
    print(f"Entities whose source_ku_ids are all deleted (report-only): {len(plan.orphan_entities)}")

    if sample_n > 0 and plan.drop_samples:
        print(f"\n=== Sample of KUs to delete (up to {sample_n}) ===")
        for ku_id, unit_type, summary in plan.drop_samples:
            print(f"  [{unit_type}] {ku_id} {summary}")

    if plan.orphan_entities:
        print("\n=== Report-only entities (NOT deleted) ===")
        for entity_id, name, ku_count in plan.orphan_entities[:20]:
            print(f"  {entity_id} {name} (source_ku_ids: {ku_count})")
        if len(plan.orphan_entities) > 20:
            print(f"  ... and {len(plan.orphan_entities) - 20} more")


def execute_plan(db_path: str, plan: PrunePlan, with_graph: bool) -> None:
    """按计划执行删除：SQLite 单事务（KU+FTS+簇+map），随后可选删图节点。"""
    ku_rows = [(ku_id,) for ku_id in sorted(plan.drop_ids)]
    cluster_rows = [(cluster_id,) for cluster_id in plan.empty_cluster_ids]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # 两表同删，防触发 FTS 全量重建（参照 KnowledgeUnitRepository._sync_fts_rows）
        conn.executemany("DELETE FROM knowledge_units WHERE ku_id = ?", ku_rows)
        conn.executemany("DELETE FROM knowledge_units_fts WHERE ku_id = ?", ku_rows)
        conn.executemany("DELETE FROM event_clusters WHERE cluster_id = ?", cluster_rows)
        conn.executemany("DELETE FROM cluster_entity_map WHERE cluster_id = ?", cluster_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Deleted {len(ku_rows)} KU rows (knowledge_units + knowledge_units_fts)")
    print(f"Deleted {len(cluster_rows)} empty cluster rows (event_clusters + cluster_entity_map)")

    if with_graph:
        # 延迟 import：KnowledgeGraphSync 依赖 neo4j，--with-graph 关闭时不得引入
        from src.knowledge_graph_sync import KnowledgeGraphSync

        sync = KnowledgeGraphSync()
        nodes_deleted = sum(
            1 for cluster_id in plan.empty_cluster_ids if sync.delete_node(cluster_id)
        )
        print(f"Deleted {nodes_deleted} EventCluster nodes from Neo4j")


def print_postflight() -> None:
    print(
        "\nPost-flight steps:\n"
        "  1. 重建向量索引（FAISS + id_map.json，产物布局参照 scripts/migrate_vectors.py；\n"
        "     用 VectorIndex.rebuild(units) 全量重建，需 embedding 配置），例：\n"
        "       uv run python -c \"\n"
        "         from src.knowledge_base import KnowledgeUnitRepository\n"
        "         from src.retrieval.embedding import OpenAICompatEmbedding\n"
        "         from src.retrieval.vector_index import VectorIndex\n"
        "         repo = KnowledgeUnitRepository('data/news.db')\n"
        "         VectorIndex('data/news.db', OpenAICompatEmbedding()).rebuild(repo.get_all())\n"
        "       \"\n"
        "  2. 重生成 eval fixture：\n"
        "       uv run python scripts/snapshot_eval_pair.py --golden eval/golden_dataset_v2.json \\\n"
        "         --source-db data/news.db --fixture tests/fixtures/eval_snapshot.db --baseline eval/baseline.json\n"
        "     golden 若含行情类期望，按刻意演进流程修订基线。\n"
        "  3. 跑 eval 回归：\n"
        "       uv run python scripts/eval_run.py --output eval/run_latest.json\n"
        "       uv run python scripts/eval_guard.py --run eval/run_latest.json"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune pure-state (quote-snapshot) knowledge units (one-time)"
    )
    parser.add_argument("--db", default="data/news.db", help="SQLite database path")
    parser.add_argument("--execute", action="store_true", default=False,
                        help="Apply the prune (default: dry-run report only)")
    parser.add_argument("--with-graph", action="store_true", default=False,
                        help="Also delete emptied EventCluster nodes from Neo4j (requires --execute)")
    parser.add_argument("--sample", type=int, default=10,
                        help="Number of to-be-deleted KU samples to print in dry-run")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        plan = build_plan(conn, args.sample)
    finally:
        conn.close()

    print()
    report(plan, args.sample, mode="EXECUTING" if args.execute else "DRY RUN")

    if not args.execute:
        if args.with_graph:
            print("\nNote: --with-graph has no effect in dry-run mode.")
        print("\nDry run only — no changes made.")
        print("Run with --execute to prune (back up first via scripts/backup.sh).")
        return 0

    print("\nWARNING: this will mutate SQLite (knowledge_units, knowledge_units_fts,")
    print("event_clusters, cluster_entity_map). Ensure you have run scripts/backup.sh")
    print("first; for --with-graph also dump Neo4j (neo4j-admin database dump).")

    execute_plan(args.db, plan, with_graph=args.with_graph)
    print_postflight()
    return 0


if __name__ == "__main__":
    sys.exit(main())
