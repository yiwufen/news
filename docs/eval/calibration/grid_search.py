"""Step 4 — Grid search over the active levers (bm25_weight × bm25_cap).

The single-variable sweep showed only bm25_weight and bm25_cap move nDCG@10
(the other 4 weights are inert in the current config — see inspect_signals.py
and REPORT.md). This grid searches the joint (bm25_weight, bm25_cap) space,
since the two interact (cap clamps the weighted value).

Primary objective: macro nDCG@10. Guardrails: Recall@20, Precision@5, zero-hit
(so we don't optimize ranking at the cost of surfacing fewer relevant items).

Also reports a bootstrap 95% CI on nDCG@10 for the top candidates, because the
28-query set is statistically thin and a 1-2pp nDCG difference may be noise.

Run:
    uv run python docs/eval/calibration/grid_search.py
"""

from __future__ import annotations

import json
import logging
import random
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rerank import (  # noqa: E402
    CALIB_DIR,
    Profile,
    evaluate_ranking,
    load_grades,
    load_queries,
    load_signals,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("calibration.grid")

# Grid: the two active levers. bm25_weight around the sweep sweet spot (0.2),
# bm25_cap spanning uncapped-ish (6,10) down to the baseline cap (3).
BM25_WEIGHTS = [0.1, 0.2, 0.3, 0.5]
BM25_CAPS = [3.0, 4.0, 6.0, 10.0]


def _bootstrap_ci(
    queries, signals, grades, profile: Profile, n_boot: int = 1000, seed: int = 0
) -> tuple[float, float]:
    """Bootstrap 95% CI on macro nDCG@10 by resampling queries with replacement."""
    rng = random.Random(seed)
    n = len(queries)
    # Precompute per-query ndcg under this profile.
    from rerank import STRUCTURAL_INTENTS, profile_for, rerank_query  # noqa: E402

    from docs.eval.scripts.metrics import compute_query_metrics  # type: ignore[import-not-found]  # noqa: E402

    per_q_ndcg = []
    for q in queries:
        qid = q["id"]
        sigs = signals.get(qid, [])
        gr = grades.get(qid, {})
        structural = q["intent"] in STRUCTURAL_INTENTS
        p = profile_for(q["intent"], override=profile)
        ranked = rerank_query(sigs, p, structural_order=structural, top_k=100)
        m = compute_query_metrics(qid, q["category"], ranked, gr)
        per_q_ndcg.append(m.ndcg10)
    means = []
    for _ in range(n_boot):
        sample = [per_q_ndcg[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return lo, hi


def main() -> None:
    queries = load_queries()
    signals = load_signals()
    grades = load_grades()

    base_overall, _, _ = evaluate_ranking(signals, grades, queries, override=None)
    base_ndcg = base_overall.ndcg10
    print("=" * 78)
    print("GRID SEARCH: bm25_weight × bm25_cap  (other fields at REF defaults)")
    print(f"Baseline (per-intent): nDCG@10={base_ndcg:.4f}  R@20={base_overall.recall20:.4f}")
    print("=" * 78)

    results = []
    for bw, bc in product(BM25_WEIGHTS, BM25_CAPS):
        p = Profile(bm25_weight=bw, bm25_cap=bc)  # other fields = defaults
        overall, by_cat, _ = evaluate_ranking(signals, grades, queries, override=p)
        results.append(
            {
                "bm25_weight": bw,
                "bm25_cap": bc,
                "ndcg10": round(overall.ndcg10, 4),
                "delta_base": round(overall.ndcg10 - base_ndcg, 4),
                "recall20": round(overall.recall20, 4),
                "precision5": round(overall.precision5, 4),
                "mrr10": round(overall.mrr10, 4),
                "zero_hit_rate": round(overall.zero_hit_rate, 4),
                "by_category": {
                    c: {"ndcg10": round(a.ndcg10, 4), "recall20": round(a.recall20, 4)}
                    for c, a in by_cat.items()
                },
            }
        )

    # Sort by nDCG desc, with Recall@20 as tiebreaker.
    results.sort(key=lambda r: (r["ndcg10"], r["recall20"]), reverse=True)

    print(f"\nTop 8 by nDCG@10 (out of {len(results)} grid points):")
    print(f"  {'bm25_w':>7} {'bm25_cap':>9} | {'nDCG@10':>8} {'Δbase':>7} "
          f"{'R@20':>7} {'P@5':>6} {'MRR':>6} {'zero%':>6}")
    print("  " + "-" * 64)
    for r in results[:8]:
        print(
            f"  {r['bm25_weight']:>7} {r['bm25_cap']:>9} | {r['ndcg10']:>8.4f} "
            f"{r['delta_base']:>+7.4f} {r['recall20']:>7.4f} "
            f"{r['precision5']:>6.4f} {r['mrr10']:>6.4f} "
            f"{r['zero_hit_rate'] * 100:>5.1f}%"
        )

    # Bootstrap CI for top 3 to judge significance.
    print("\nBootstrap 95% CI on macro nDCG@10 (top 3 + baseline):")
    top3 = results[:3]
    for r in top3:
        p = Profile(bm25_weight=r["bm25_weight"], bm25_cap=r["bm25_cap"])
        lo, hi = _bootstrap_ci(queries, signals, grades, p)
        print(f"  bm25_w={r['bm25_weight']:<4} cap={r['bm25_cap']:<5} "
              f"nDCG={r['ndcg10']:.4f}  CI=[{lo:.4f}, {hi:.4f}]")
    # Baseline CI (per-intent) — approximate by sampling under per-intent.
    # For comparability, evaluate baseline as-is.
    lo, hi = _bootstrap_ci_baseline(queries, signals, grades)
    print(f"  baseline (per-intent)       nDCG={base_ndcg:.4f}  CI=[{lo:.4f}, {hi:.4f}]")

    out = CALIB_DIR / "grid_search.grid.json"
    out.write_text(
        json.dumps(
            {
                "baseline_ndcg10": round(base_ndcg, 4),
                "grid": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s", out.name)


def _bootstrap_ci_baseline(queries, signals, grades, n_boot: int = 1000, seed: int = 0):
    """Bootstrap CI under baseline per-intent profiles (override=None)."""
    from rerank import STRUCTURAL_INTENTS, BASELINE_PROFILES, rerank_query  # noqa: E402
    from docs.eval.scripts.metrics import compute_query_metrics  # type: ignore[import-not-found]  # noqa: E402

    rng = random.Random(seed)
    n = len(queries)
    per_q = []
    for q in queries:
        qid = q["id"]
        sigs = signals.get(qid, [])
        gr = grades.get(qid, {})
        structural = q["intent"] in STRUCTURAL_INTENTS
        p = BASELINE_PROFILES.get(q["intent"], Profile())
        ranked = rerank_query(sigs, p, structural_order=structural, top_k=100)
        per_q.append(compute_query_metrics(qid, q["category"], ranked, gr).ndcg10)
    means = sorted(
        sum(per_q[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot)
    )
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


if __name__ == "__main__":
    main()
