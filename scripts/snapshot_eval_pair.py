"""
导出 golden 评估数据集所依赖的 fixture DB 子集。

本脚本在「真实数据库」上运行一次（通常在远程服务器），从 golden 数据集中收集
所有出现的 KU id（ground truth + 每条 query 的 top_ku_ids），抽取这些 KU 及其
关联的 Entity / EventCluster，写入一个独立的 SQLite 文件，作为本地 EDD 回归的
fixture DB。fixture DB 与 golden 数据集通过 sha256 互相锁定，写入 baseline.json。

用法（在拥有真实 data/news.db 的环境运行）::

    uv run python scripts/snapshot_eval_pair.py \\
        --golden eval/golden_dataset_v2.json \\
        --source-db data/news.db \\
        --fixture tests/fixtures/eval_snapshot.db \\
        --baseline eval/baseline.json

产物：
- ``--fixture``：子集 SQLite 文件（入 Git）
- ``--baseline``：记录两个 sha256 + 基线元信息（指标由 eval_run.py 首跑填入）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# 让脚本能从仓库根直接 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.entities import EntityRepository
from src.event_merging import EventClusterRepository
from src.knowledge_base import KnowledgeUnit, KnowledgeUnitRepository


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_ku_ids(dataset: dict[str, Any]) -> set[str]:
    """收集 golden 集中所有出现的 KU id：每条 item 的 ground truth + 每条 query 的 top_ku_ids。"""
    ku_ids: set[str] = set()
    for item in dataset.get("items", []):
        gt = item.get("ground_truth_ku", {})
        if gt.get("ku_id"):
            ku_ids.add(gt["ku_id"])
        for q in item.get("queries", []):
            retrieval = q.get("retrieval", {})
            ku_ids.update(retrieval.get("top_ku_ids", []))
    return ku_ids


def collect_referenced_entities(kus: list[KnowledgeUnit]) -> set[str]:
    """从一批 KU 中收集所有引用到的 entity_id（非空）。"""
    ids: set[str] = set()
    for ku in kus:
        for ref in ku.entities:
            if ref.entity_id:
                ids.add(ref.entity_id)
    return ids


def collect_cluster_ids(kus: list[KnowledgeUnit]) -> set[str]:
    """从一批 KU 中收集所有非空 cluster_id。"""
    ids: set[str] = set()
    for ku in kus:
        if ku.cluster_id:
            ids.add(ku.cluster_id)
    return ids


def build_fixture(
    dataset: dict[str, Any],
    source_db: str,
    fixture_path: Path,
) -> dict[str, Any]:
    """从 source_db 抽取子集写入 fixture_path，返回抽取统计。"""
    # 目标文件必须干净：删除后由 repo __init__ 自动重建 schema
    if fixture_path.exists():
        fixture_path.unlink()
    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    ku_repo_src = KnowledgeUnitRepository(source_db)
    ent_repo_src = EntityRepository(source_db)
    cluster_repo_src = EventClusterRepository(source_db)

    target_ku_str = str(fixture_path)
    ku_repo_dst = KnowledgeUnitRepository(target_ku_str)
    ent_repo_dst = EntityRepository(target_ku_str)
    cluster_repo_dst = EventClusterRepository(target_ku_str, knowledge_units=ku_repo_dst)

    # 1. 抽取 KU 子集
    target_ku_ids = collect_ku_ids(dataset)
    kus = ku_repo_src.get_by_ids(list(target_ku_ids))
    found_ku_ids = {ku.ku_id for ku in kus}
    missing = target_ku_ids - found_ku_ids
    if missing:
        print(
            f"  ⚠  {len(missing)} 个目标 KU 在源库中不存在（将跳过）："
            f"{sorted(missing)[:5]}{' ...' if len(missing) > 5 else ''}",
            file=sys.stderr,
        )
    ku_repo_dst.save_batch(kus)

    # 2. 抽取关联 Entity
    entity_ids = collect_referenced_entities(kus)
    entities = ent_repo_src.get_by_ids(list(entity_ids)) if entity_ids else []
    ent_repo_dst.save_batch(entities)

    # 3. 抽取关联 EventCluster
    cluster_ids = collect_cluster_ids(kus)
    clusters = cluster_repo_src.get_by_ids(list(cluster_ids)) if cluster_ids else []
    cluster_repo_dst.save_batch(clusters)

    return {
        "kus_in_golden": len(target_ku_ids),
        "kus_extracted": len(kus),
        "entities_extracted": len(entities),
        "clusters_extracted": len(clusters),
    }


def write_baseline_skeleton(
    baseline_path: Path,
    golden_path: Path,
    fixture_path: Path,
    stats: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    """写入 baseline.json 骨架（含 hash 锁；metrics 字段留空，由 eval_run.py --init 填入）。"""
    baseline: dict[str, Any] = {
        "version": "1.0",
        "golden_dataset_path": str(golden_path).replace("\\", "/"),
        "golden_dataset_sha256": _sha256_text(golden_path.read_text(encoding="utf-8")),
        "fixture_db_path": str(fixture_path).replace("\\", "/"),
        "fixture_db_sha256": _sha256_file(fixture_path),
        "snapshot_stats": stats,
        "snapshot_metadata": {
            "db_path": metadata.get("db_path"),
            "graph_enabled": metadata.get("graph_enabled", False),
            "top_k": metadata.get("top_k", 20),
        },
        # 由 eval_run.py --init-baseline 填入
        "metrics": None,
        "created_at": metadata.get("created_at"),
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 golden 数据集的 fixture DB 子集")
    parser.add_argument(
        "--golden", default="eval/golden_dataset_v2.json", help="golden 数据集 JSON"
    )
    parser.add_argument(
        "--source-db", default="data/news.db", help="真实知识库 SQLite 路径"
    )
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/eval_snapshot.db",
        help="输出的 fixture DB 路径",
    )
    parser.add_argument(
        "--baseline", default="eval/baseline.json", help="输出的 baseline JSON 路径"
    )
    args = parser.parse_args()

    golden_path = Path(args.golden)
    fixture_path = Path(args.fixture)
    baseline_path = Path(args.baseline)
    source_db = args.source_db

    if not golden_path.exists():
        print(f"  ✗ golden 数据集不存在：{golden_path}", file=sys.stderr)
        return 2
    if not Path(source_db).exists():
        print(f"  ✗ 源数据库不存在：{source_db}", file=sys.stderr)
        return 2

    dataset = json.loads(golden_path.read_text(encoding="utf-8"))
    metadata = dataset.get("metadata", {})

    print(f"  · 源库：{source_db}")
    print(f"  · golden：{golden_path}")
    stats = build_fixture(dataset, source_db, fixture_path)
    fixture_size_mb = fixture_path.stat().st_size / (1 << 20)
    print(
        f"  · fixture 写入：{fixture_path} "
        f"({fixture_size_mb:.2f} MB | "
        f"KU {stats['kus_extracted']}/{stats['kus_in_golden']} | "
        f"Entity {stats['entities_extracted']} | "
        f"Cluster {stats['clusters_extracted']})"
    )

    write_baseline_skeleton(baseline_path, golden_path, fixture_path, stats, metadata)
    print(f"  · baseline 骨架写入：{baseline_path}（metrics 待 eval_run.py --init 填入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
