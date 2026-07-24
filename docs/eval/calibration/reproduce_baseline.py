"""Step 2 — Correctness gate: reproduce the baseline metrics from cached signals.

MUST match ``docs/eval/results/20260702_110009_report.txt`` (macro nDCG@10 =
0.6336, etc.) within tolerance before trusting any weight sweep. If this fails,
the re-ranking engine diverges from production scoring and all downstream
numbers are invalid.

Run:
    uv run python docs/eval/calibration/reproduce_baseline.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rerank import evaluate_ranking, load_grades, load_queries, load_signals  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("calibration.reproduce")


# Target values from docs/eval/results/20260702_110009_report.txt (28 queries).
TARGET = {
    "n_queries": 28,
    "ndcg10": 0.6336,
    "recall5": 0.1585,
    "recall20": 0.4498,
    "mrr10": 0.7500,
    "precision5": 0.6571,
    "zero_hit_rate": 0.0714,
}
# Per-category targets.
TARGET_BY_CAT = {
    "alias_resolution":       {"ndcg10": 0.7556, "recall20": 0.4317},
    "comparative":            {"ndcg10": 0.2521, "recall20": 0.2237},
    "intent_contrast":        {"ndcg10": 0.9242, "recall20": 0.3000},
    "parameterized":          {"ndcg10": 0.7007, "recall20": 0.7407},
    "single_entity_baseline": {"ndcg10": 0.8701, "recall20": 0.6251},
    "topic_no_entity":        {"ndcg10": 0.3403, "recall20": 0.2864},
}
TOL = 0.01


def main() -> None:
    queries = load_queries()
    signals = load_signals()
    grades = load_grades()
    logger.info(
        "Loaded %d queries, %d signal pools, %d grade pools",
        len(queries), len(signals), len(grades),
    )

    # override=None → use baseline per-intent profiles.
    overall, by_cat, per_query = evaluate_ranking(
        signals, grades, queries, override=None,
    )

    print("=" * 64)
    print("BASELINE REPRODUCTION (default INTENT_PROFILES)")
    print("=" * 64)
    print(f"  n_queries    : {overall.n_queries}  (target {TARGET['n_queries']})")
    print(f"  nDCG@10      : {overall.ndcg10:.4f}  (target {TARGET['ndcg10']:.4f})")
    print(f"  Recall@5     : {overall.recall5:.4f}  (target {TARGET['recall5']:.4f})")
    print(f"  Recall@20    : {overall.recall20:.4f}  (target {TARGET['recall20']:.4f})")
    print(f"  MRR@10       : {overall.mrr10:.4f}  (target {TARGET['mrr10']:.4f})")
    print(f"  Precision@5  : {overall.precision5:.4f}  (target {TARGET['precision5']:.4f})")
    print(f"  zero-hit rate: {overall.zero_hit_rate:.4f}  (target {TARGET['zero_hit_rate']:.4f})")
    print()
    print("By category (nDCG@10 / Recall@20):")
    for cat in sorted(by_cat):
        agg = by_cat[cat]
        tgt = TARGET_BY_CAT.get(cat, {})
        print(
            f"  {cat:<26} nDCG={agg.ndcg10:.4f}(tgt {tgt.get('ndcg10', 0):.4f})  "
            f"R@20={agg.recall20:.4f}(tgt {tgt.get('recall20', 0):.4f})"
        )

    # Gate check.
    print()
    checks = [
        ("n_queries", overall.n_queries, TARGET["n_queries"]),
        ("nDCG@10", overall.ndcg10, TARGET["ndcg10"]),
        ("Recall@5", overall.recall5, TARGET["recall5"]),
        ("Recall@20", overall.recall20, TARGET["recall20"]),
        ("MRR@10", overall.mrr10, TARGET["mrr10"]),
        ("Precision@5", overall.precision5, TARGET["precision5"]),
        ("zero-hit", overall.zero_hit_rate, TARGET["zero_hit_rate"]),
    ]
    failed = []
    for name, got, want in checks:
        ok = abs(got - want) < TOL if isinstance(got, float) else got == want
        flag = "OK " if ok else "FAIL"
        if not ok:
            failed.append(name)
        print(f"  [{flag}] {name:<12} got={got} want={want} (tol {TOL})")

    # Per-query exact-match check on nDCG (most sensitive to ordering).
    pq_by_id = {m.query_id: m for m in per_query}
    # Reconstruct target per-query nDCG from the report.
    target_pq = {
        "Q01": 0.8359, "Q02": 0.8780, "Q03": 0.7740, "Q04": 1.0000,
        "Q05": 0.8880, "Q06": 1.0000, "Q07": 0.6910, "Q08": 0.8940,
        "Q09": 1.0000, "Q10": 1.0000, "Q11": 1.0000, "Q12": 0.0000,
        "Q13": 0.7780, "Q14": 0.7660, "Q15": 0.8910, "Q16": 0.0550,
        "Q17": 0.0000, "Q18": 0.3300, "Q19": 0.0000, "Q20": 0.4920,
        "Q21": 0.0000, "Q22": 0.5160, "Q23": 0.0000, "Q26": 1.0000,
        "Q27": 0.8480, "Q28": 1.0000, "Q29": 0.7330, "Q30": 0.3690,
    }
    pq_bad = []
    for qid, want in target_pq.items():
        got = pq_by_id.get(qid)
        if got is None:
            pq_bad.append(f"{qid}(missing)")
        elif abs(got.ndcg10 - want) >= TOL:
            pq_bad.append(f"{qid}(got {got.ndcg10:.3f} want {want:.3f})")

    print()
    if pq_bad:
        print(f"  Per-query nDCG mismatches ({len(pq_bad)}): {', '.join(pq_bad[:10])}")
    else:
        print("  All 28 per-query nDCG@10 match within tol — ordering reproduced.")

    if failed or pq_bad:
        print("\nGATE FAILED — do not trust downstream sweeps until fixed.")
        sys.exit(1)
    else:
        print("\nGATE PASSED — re-ranking engine faithfully reproduces baseline.")


if __name__ == "__main__":
    main()
