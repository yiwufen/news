"""
黄金数据集指标报告。

从已标注（或预标注）数据集计算 NDCG / Recall@K / MRR 等指标。

用法:
    uv run python scripts/eval_report.py --input eval/golden_dataset_v1.json
    uv run python scripts/eval_report.py --input eval/golden_dataset_v1_labeled.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_dataset(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _get_label(query: dict[str, Any]) -> int:
    """优先用 human_label，其次 llm_label，最后 pre_label。"""
    return (
        query.get("human_label")
        or query.get("llm_label")
        or query.get("pre_label")
        or 0
    )


def _get_label_source(query: dict[str, Any]) -> str:
    if query.get("human_label") is not None:
        return "human"
    if query.get("llm_label") is not None:
        return "llm"
    return "rule"


# ── 指标计算 ──────────────────────────────────────────────

def recall_at_k(queries: list[dict[str, Any]], k: int) -> float:
    """Ground truth KU 在 Top-K 中出现的比例。"""
    if not queries:
        return 0.0
    hits = sum(
        1
        for q in queries
        if q["retrieval"]["ground_truth_rank"] is not None
        and q["retrieval"]["ground_truth_rank"] <= k
    )
    return hits / len(queries)


def mrr(queries: list[dict[str, Any]]) -> float:
    """Mean Reciprocal Rank。"""
    if not queries:
        return 0.0
    total = 0.0
    for q in queries:
        rank = q["retrieval"]["ground_truth_rank"]
        if rank is not None:
            total += 1.0 / rank
    return total / len(queries)


def ndcg_at_k(queries: list[dict[str, Any]], k: int) -> float:
    """NDCG@K 基于 ground truth 排名 + 人工标注分数。"""
    if not queries:
        return 0.0

    total = 0.0
    count = 0
    for q in queries:
        label = _get_label(q)
        rank = q["retrieval"]["ground_truth_rank"]

        # DCG: ground truth 的 gain 取决于其排名位置
        if rank is not None and rank <= k:
            dcg = label / math.log2(rank + 1)
        else:
            dcg = 0.0

        # Ideal: ground truth 排第 1 名
        idcg = label / math.log2(2)  # log2(1+1) = 1

        if idcg > 0:
            total += dcg / idcg
            count += 1

    return total / count if count > 0 else 0.0


def mean_label(queries: list[dict[str, Any]]) -> float:
    """平均相关性评分 (0-3)。"""
    if not queries:
        return 0.0
    return sum(_get_label(q) for q in queries) / len(queries)


def label_distribution(queries: list[dict[str, Any]]) -> dict[str, int]:
    """标签分布统计。"""
    dist: dict[int, int] = defaultdict(int)
    for q in queries:
        dist[_get_label(q)] += 1
    return {f"label_{k}": v for k, v in sorted(dist.items())}


def failure_analysis(queries: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """收集失败的查询（label=0 或 ground truth 未找到）。"""
    failures = []
    for item in items:
        for q in item["queries"]:
            label = _get_label(q)
            gt_found = q["retrieval"]["ground_truth_found"]
            if label == 0 or not gt_found:
                failures.append({
                    "item_id": item["item_id"],
                    "query_text": q["query_text"],
                    "query_type": q["query_type"],
                    "difficulty": q["difficulty"],
                    "label": label,
                    "label_source": _get_label_source(q),
                    "ground_truth_rank": q["retrieval"]["ground_truth_rank"],
                    "ground_truth_found": gt_found,
                    "ground_truth_summary": item["ground_truth_ku"]["summary"][:80],
                })
    return failures


# ── 报告输出 ──────────────────────────────────────────────

def print_report(dataset: dict[str, Any]) -> None:
    """打印完整的评估报告。"""
    items = dataset["items"]
    all_queries = [q for it in items for q in it["queries"]]

    # 标注覆盖率
    human_count = sum(1 for q in all_queries if q.get("human_label") is not None)
    llm_count = sum(1 for q in all_queries if q.get("llm_label") is not None and q.get("human_label") is None)
    rule_count = len(all_queries) - human_count - llm_count

    print("=" * 60)
    print("  黄金数据集评估报告")
    print("=" * 60)
    print(f"\n  数据集版本: {dataset.get('version', '?')}")
    print(f"  生成时间:   {dataset.get('created_at', '?')}")
    print(f"  Items:      {len(items)}")
    print(f"  查询总数:   {len(all_queries)}")
    print(f"  标注来源:   人工={human_count}, LLM={llm_count}, 规则={rule_count}")

    # 全局指标
    print(f"\n{'─' * 60}")
    print("  全局指标")
    print(f"{'─' * 60}")
    print(f"  Recall@1:   {recall_at_k(all_queries, 1):.3f}")
    print(f"  Recall@5:   {recall_at_k(all_queries, 5):.3f}")
    print(f"  Recall@10:  {recall_at_k(all_queries, 10):.3f}")
    print(f"  Recall@20:  {recall_at_k(all_queries, 20):.3f}")
    print(f"  MRR:        {mrr(all_queries):.3f}")
    print(f"  NDCG@5:     {ndcg_at_k(all_queries, 5):.3f}")
    print(f"  NDCG@10:    {ndcg_at_k(all_queries, 10):.3f}")
    print(f"  平均评分:   {mean_label(all_queries):.2f} / 3.0")
    print(f"  标签分布:   {label_distribution(all_queries)}")

    # 按 query_type 分组
    print(f"\n{'─' * 60}")
    print("  按 query_type 分组")
    print(f"{'─' * 60}")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for q in all_queries:
        by_type[q.get("query_type", "unknown")].append(q)

    print(f"  {'类型':<20} {'数量':>4} {'Recall@5':>9} {'MRR':>6} {'NDCG@10':>8} {'均分':>5}")
    print(f"  {'─' * 55}")
    for qtype in sorted(by_type.keys()):
        qs = by_type[qtype]
        print(
            f"  {qtype:<20} {len(qs):>4} "
            f"{recall_at_k(qs, 5):>9.3f} "
            f"{mrr(qs):>6.3f} "
            f"{ndcg_at_k(qs, 10):>8.3f} "
            f"{mean_label(qs):>5.2f}"
        )

    # 按 difficulty 分组
    print(f"\n{'─' * 60}")
    print("  按 difficulty 分组")
    print(f"{'─' * 60}")
    by_diff: dict[str, list[dict]] = defaultdict(list)
    for q in all_queries:
        by_diff[q.get("difficulty", "unknown")].append(q)

    print(f"  {'难度':<10} {'数量':>4} {'Recall@5':>9} {'MRR':>6} {'NDCG@10':>8} {'均分':>5}")
    print(f"  {'─' * 45}")
    for diff in ["easy", "medium", "hard"]:
        if diff in by_diff:
            qs = by_diff[diff]
            print(
                f"  {diff:<10} {len(qs):>4} "
                f"{recall_at_k(qs, 5):>9.3f} "
                f"{mrr(qs):>6.3f} "
                f"{ndcg_at_k(qs, 10):>8.3f} "
                f"{mean_label(qs):>5.2f}"
            )

    # 失败分析
    print(f"\n{'─' * 60}")
    print("  失败分析")
    print(f"{'─' * 60}")
    failures = failure_analysis(all_queries, items)
    if not failures:
        print("  无失败查询")
    else:
        print(f"  失败查询数: {len(failures)}")
        for f in failures[:10]:
            gt_str = f"rank={f['ground_truth_rank']}" if f['ground_truth_rank'] else "未找到"
            print(f"  - [{f['query_type']}/{f['difficulty']}] \"{f['query_text'][:40]}\" → {gt_str} (label={f['label']})")
        if len(failures) > 10:
            print(f"  ... 还有 {len(failures) - 10} 条")

    print(f"\n{'=' * 60}")


def check_freshness(dataset: dict[str, Any], db_path: str = "data/news.db") -> int:
    """Check how many ground truth KUs still exist in the database.

    Returns the number of missing KU IDs.  Prints a warning if any are stale.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.knowledge_base import KnowledgeUnitRepository

    repo = KnowledgeUnitRepository(db_path)
    all_ids = {ku.ku_id for ku in repo.get_all()}
    items = dataset.get("items", [])
    missing = sum(1 for it in items if it["ground_truth_ku"]["ku_id"] not in all_ids)
    total = len(items)

    if missing > 0:
        pct = missing / total * 100 if total else 0
        print(f"\n  ⚠  数据集过期: {missing}/{total} ({pct:.0f}%) ground truth KU 已不在当前知识库中")
        print(f"     生成时间: {dataset.get('created_at', '?')}")
        print(f"     请重新运行 eval_generate.py 以生成新数据集\n")
    else:
        print(f"  [OK] 数据集新鲜度检查通过: {total}/{total} ground truth KU 有效")
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="黄金数据集指标报告")
    parser.add_argument("--input", required=True, help="数据集 JSON 路径")
    parser.add_argument("--db", default="data/news.db", help="知识库路径（新鲜度检查）")
    parser.add_argument("--skip-freshness", action="store_true", help="跳过新鲜度检查")
    args = parser.parse_args()

    dataset = _load_dataset(args.input)

    if not args.skip_freshness:
        missing = check_freshness(dataset, args.db)
        if missing > 0:
            print("  (使用 --skip-freshness 强制显示过期数据集的报告)\n")

    print_report(dataset)


if __name__ == "__main__":
    main()
