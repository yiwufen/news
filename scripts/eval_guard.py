"""
EDD 自动回归门禁。

对比 ``eval_run.py`` 的本次运行结果（``--output`` 产物或 eval/baseline.json 的
metrics 字段）与 ``eval/baseline.json`` 中钉死的基线，超标则非零退出。

门禁规则（对齐 .zcode/rules/retrieval-code.md）：
- fixture_db_sha256 / golden_dataset_sha256 与 baseline 不符 → 硬失败（漂移）
- 全局 Recall@5 下降 > RECALL5_GLOBAL_TOL → FAIL
- 任一 query_type Recall@5 下降 > RECALL5_TYPE_TOL → FAIL
- MRR 下降 > MRR_WARN_TOL → WARN（打印，不阻断）

用法::

    # 1. 先跑 eval_run 产出本次结果
    uv run python scripts/eval_run.py --output eval/run_latest.json

    # 2. 门禁对比
    uv run python scripts/eval_guard.py --run eval/run_latest.json
    # 或直接读 baseline.json 自身的 metrics 做自洽检查
    uv run python scripts/eval_guard.py --baseline eval/baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 阈值（百分点 / 小数）
RECALL5_GLOBAL_TOL = 0.02  # 全局 Recall@5 下降超过 2pp → FAIL
RECALL5_TYPE_TOL = 0.05  # 单 query_type Recall@5 下降超过 5pp → FAIL
MRR_WARN_TOL = 0.03  # MRR 下降超过 0.03 → WARN


def _pp(x: float) -> str:
    return f"{x:.3f}"


def _delta_pp(cur: float, base: float) -> float:
    """当前相对基线的「下降幅度」（正数=退步）。"""
    return base - cur


def check_hashes(run: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """hash 锁校验。返回错误信息列表（空=通过）。"""
    errors: list[str] = []
    for key in ("fixture_db_sha256", "golden_dataset_sha256"):
        if run.get(key) != baseline.get(key):
            errors.append(
                f"{key} 漂移：baseline={baseline.get(key)} ≠ run={run.get(key)}\n"
                f"     数据集或 fixture 已变化。若为有意更新，请重跑 "
                f"snapshot_eval_pair.py + eval_run.py --init-baseline 刷新 baseline。"
            )
    return errors


def compare_metrics(
    cur: dict[str, Any], base: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    """对比指标。返回 (fails, warns, notes)。"""
    fails: list[str] = []
    warns: list[str] = []
    notes: list[str] = []

    cur_ov = cur["overall"]
    base_ov = base["overall"]

    d_r5 = _delta_pp(cur_ov["recall_at_5"], base_ov["recall_at_5"])
    notes.append(
        f"全局 Recall@5: {_pp(cur_ov['recall_at_5'])} (base {_pp(base_ov['recall_at_5'])}, "
        f"Δ {d_r5:+.3f})"
    )
    if d_r5 > RECALL5_GLOBAL_TOL:
        fails.append(
            f"全局 Recall@5 下降 {d_r5*100:.1f}pp > {RECALL5_GLOBAL_TOL*100:.0f}pp 阈值"
        )

    d_mrr = _delta_pp(cur_ov["mrr"], base_ov["mrr"])
    if d_mrr > MRR_WARN_TOL:
        warns.append(f"全局 MRR 下降 {d_mrr:.3f} > {MRR_WARN_TOL}（WARN，不阻断）")

    # 按 query_type
    base_by_type = base.get("by_query_type", {})
    cur_by_type = cur.get("by_query_type", {})
    for qtype, bm in base_by_type.items():
        cm = cur_by_type.get(qtype)
        if cm is None:
            warns.append(f"query_type '{qtype}' 在本次运行中缺失（无法对比）")
            continue
        d = _delta_pp(cm["recall_at_5"], bm["recall_at_5"])
        if d > RECALL5_TYPE_TOL:
            fails.append(
                f"query_type '{qtype}' Recall@5 下降 {d*100:.1f}pp > "
                f"{RECALL5_TYPE_TOL*100:.0f}pp 阈值 "
                f"({_pp(cm['recall_at_5'])} vs base {_pp(bm['recall_at_5'])})"
            )
    return fails, warns, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="EDD 自动回归门禁")
    parser.add_argument(
        "--run",
        default="eval/run_latest.json",
        help="eval_run.py 本次运行产物（含 metrics + sha256）",
    )
    parser.add_argument(
        "--baseline", default="eval/baseline.json", help="基线 JSON"
    )
    args = parser.parse_args()

    run_path = Path(args.run)
    baseline_path = Path(args.baseline)
    if not run_path.exists():
        print(
            f"  ✗ 运行结果不存在：{run_path}\n"
            f"     请先运行：uv run python scripts/eval_run.py --output {run_path}",
            file=sys.stderr,
        )
        return 2
    if not baseline_path.exists():
        print(f"  ✗ baseline 不存在：{baseline_path}", file=sys.stderr)
        return 2

    run = json.loads(run_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    if not baseline.get("metrics"):
        print(
            f"  ✗ baseline.metrics 为空：{baseline_path}\n"
            f"     请先运行：uv run python scripts/eval_run.py --init-baseline",
            file=sys.stderr,
        )
        return 2

    print("\n" + "=" * 60)
    print("EDD 回归门禁")
    print("=" * 60)

    # 1. hash 锁（漂移即硬失败）
    hash_errors = check_hashes(run, baseline)
    if hash_errors:
        print("\n  ✗ HASH 漂移（硬失败）：")
        for e in hash_errors:
            print(f"     - {e}")
        print("\n  结果：FAIL（数据集漂移，指标不可比）")
        return 1

    # 2. 指标对比
    fails, warns, notes = compare_metrics(run["metrics"], baseline["metrics"])
    for n in notes:
        print(f"  · {n}")

    if warns:
        print("\n  ⚠ WARN：")
        for w in warns:
            print(f"     - {w}")

    if fails:
        print("\n  ✗ FAIL：")
        for f in fails:
            print(f"     - {f}")
        print("\n  结果：FAIL（检索质量退化超阈值）")
        return 1

    print("\n  结果：PASS（未检测到超阈值退化）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
