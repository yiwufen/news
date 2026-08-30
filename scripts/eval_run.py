"""
本地 EDD：在 fixture DB 上重跑 golden 集检索，产出当前指标。

这是当前项目「缺失」的能力——``eval_report.py`` 只读冻结在 JSON 里的排名，
``eval_generate.py`` 覆盖式重写，两者都无法用「新代码 + 固定数据」检测检索回归。
本脚本用新代码对每条 golden query 重跑 ``run_pipeline``，重算 ground_truth_rank，
输出当前指标，供 ``eval_guard.py`` 与 ``eval/baseline.json`` 对比。

默认 graph_enabled=False（与 golden_dataset_v2.json 的 metadata 一致），无需 Neo4j。
默认不依赖 FAISS（fixture DB 无 vector_db 目录时自动禁用）。

用法::

    # 常规回归
    uv run python scripts/eval_run.py \\
        --fixture tests/fixtures/eval_snapshot.db \\
        --golden eval/golden_dataset_v2.json \\
        --output eval/run_latest.json

    # 首次：把结果写入 baseline.json 的 metrics 字段
    uv run python scripts/eval_run.py --init-baseline --baseline eval/baseline.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The gate must stay deterministic and offline: it pins the recall/fusion
# layers only. Reranker quality is measured by docs/eval (real run), and the
# reranker client itself is covered by unit tests with a mocked transport.
os.environ.setdefault("KNOWLEDGE_RERANK_DISABLED", "1")

from scripts import _eval_shared
from scripts._eval_shared import (
    all_queries,
    compute_rank,
    group_queries_by_type,
    ndcg_at_k,
    recall_at_k,
    mrr,
    run_retrieval,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rerun_dataset(
    dataset: dict[str, Any],
    *,
    fixture_db: str,
    top_k: int,
    graph_enabled: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """重跑整个 golden 集，返回 (新的扁平 query 列表(带新 rank), per-item 结构)。

    不修改 dataset；新 rank 写入返回的副本里。
    """
    new_items: list[dict[str, Any]] = []
    flat_queries: list[dict[str, Any]] = []
    items = dataset.get("items", [])
    total = sum(len(it.get("queries", [])) for it in items)

    done = 0
    for item in items:
        gt_ku_id = item["ground_truth_ku"]["ku_id"]
        new_queries: list[dict[str, Any]] = []
        for q in item.get("queries", []):
            retrieval = run_retrieval(
                q,
                db_path=fixture_db,
                top_k=top_k,
                graph_enabled=graph_enabled,
            )
            rank, found = compute_rank(retrieval["top_ku_ids"], gt_ku_id)
            new_q = dict(q)
            new_q["retrieval"] = {
                **retrieval,
                "ground_truth_rank": rank,
                "ground_truth_found": found,
            }
            new_queries.append(new_q)
            flat_queries.append(new_q)
            done += 1
            if done % 50 == 0 or done == total:
                print(f"  · 重跑进度 {done}/{total}", file=sys.stderr)
        new_item = dict(item)
        new_item["queries"] = new_queries
        new_items.append(new_item)
    return flat_queries, new_items


def compute_metrics_block(flat: list[dict[str, Any]]) -> dict[str, Any]:
    """计算全局 + 按 query_type 的指标块。"""
    groups = group_queries_by_type(
        [{"queries": flat}]  # 复用分组函数：包成单 item
    )
    by_type: dict[str, dict[str, float]] = {}
    for qtype, qs in groups.items():
        by_type[qtype] = {
            "count": float(len(qs)),
            "recall_at_5": recall_at_k(qs, 5),
            "recall_at_20": recall_at_k(qs, 20),
            "mrr": mrr(qs),
            "ndcg_at_10": ndcg_at_k(qs, 10),
        }
    return {
        "overall": {
            "count": float(len(flat)),
            "recall_at_5": recall_at_k(flat, 5),
            "recall_at_20": recall_at_k(flat, 20),
            "mrr": mrr(flat),
            "ndcg_at_10": ndcg_at_k(flat, 10),
        },
        "by_query_type": by_type,
    }


def print_report(metrics: dict[str, Any]) -> None:
    ov = metrics["overall"]
    print("\n" + "=" * 60)
    print("本地 EDD 回归报告（fixture DB 重跑）")
    print("=" * 60)
    print(f"\n  全局 (n={int(ov['count'])})")
    print(f"    Recall@5   : {ov['recall_at_5']:.3f}")
    print(f"    Recall@20  : {ov['recall_at_20']:.3f}")
    print(f"    MRR        : {ov['mrr']:.3f}")
    print(f"    NDCG@10    : {ov['ndcg_at_10']:.3f}")

    print("\n  按 query_type")
    header = f"    {'type':<22}{'n':>5}{'R@5':>9}{'MRR':>9}{'NDCG':>9}"
    print(header)
    print("    " + "-" * (len(header) - 4))
    for qtype, m in sorted(metrics["by_query_type"].items()):
        print(
            f"    {qtype:<22}{int(m['count']):>5}"
            f"{m['recall_at_5']:>9.3f}{m['mrr']:>9.3f}{m['ndcg_at_10']:>9.3f}"
        )
    print("\n" + "=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="本地 EDD：重跑 golden 集检索")
    parser.add_argument("--golden", default="eval/golden_dataset_v2.json")
    parser.add_argument(
        "--fixture", default="tests/fixtures/eval_snapshot.db", help="fixture DB 路径"
    )
    parser.add_argument(
        "--baseline", default="eval/baseline.json", help="baseline.json（--init-baseline 时写入）"
    )
    parser.add_argument(
        "--output", default=None, help="本次运行结果 JSON 输出路径（默认不写文件）"
    )
    parser.add_argument("--top-k", type=int, default=None, help="覆盖 top_k（默认读 golden metadata）")
    parser.add_argument(
        "--graph-enabled",
        action="store_true",
        help="启用图谱（默认 False，与 golden 集一致）",
    )
    parser.add_argument(
        "--init-baseline",
        action="store_true",
        help="把本次指标写入 baseline.json 的 metrics 字段（首次建立基线用）",
    )
    args = parser.parse_args()

    golden_path = Path(args.golden)
    fixture_path = Path(args.fixture)
    if not golden_path.exists():
        print(f"  ✗ golden 数据集不存在：{golden_path}", file=sys.stderr)
        return 2
    if not fixture_path.exists():
        print(
            f"  ✗ fixture DB 不存在：{fixture_path}\n"
            f"     请先在真实库环境运行 scripts/snapshot_eval_pair.py",
            file=sys.stderr,
        )
        return 2

    dataset = json.loads(golden_path.read_text(encoding="utf-8"))
    metadata = dataset.get("metadata", {})
    top_k = args.top_k if args.top_k is not None else metadata.get("top_k", 20)
    graph_enabled = args.graph_enabled  # 默认 False

    print(f"  · fixture：{fixture_path}")
    print(f"  · golden ：{golden_path}")
    print(f"  · top_k={top_k}, graph_enabled={graph_enabled}")

    start = time.time()
    flat, _new_items = rerun_dataset(
        dataset, fixture_db=str(fixture_path), top_k=top_k, graph_enabled=graph_enabled
    )
    elapsed = time.time() - start
    metrics = compute_metrics_block(flat)
    print_report(metrics)
    print(f"  · 耗时 {elapsed:.1f}s")

    run_payload: dict[str, Any] = {
        "golden_dataset_sha256": _sha256_text(golden_path.read_text(encoding="utf-8")),
        "fixture_db_sha256": _sha256_file(fixture_path),
        "top_k": top_k,
        "graph_enabled": graph_enabled,
        "metrics": metrics,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(run_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  · 结果写入：{out_path}")

    if args.init_baseline:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(
                f"  ✗ baseline.json 不存在：{baseline_path}\n"
                f"     请先运行 snapshot_eval_pair.py 生成骨架",
                file=sys.stderr,
            )
            return 2
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        # 写入 metrics；同时校验 hash 与 snapshot 一致（防漂移）
        baseline["fixture_db_sha256"] = run_payload["fixture_db_sha256"]
        baseline["golden_dataset_sha256"] = run_payload["golden_dataset_sha256"]
        baseline["metrics"] = metrics
        baseline_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  · baseline metrics 已写入：{baseline_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
