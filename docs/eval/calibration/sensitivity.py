"""Step 3 — Single-variable sensitivity sweeps over the 6 ScoringProfile weights.

For each weight, sweep a range while holding the others at baseline, and report
how macro nDCG@10 / Recall@20 / zero-hit / Precision@5 respond. This answers:
  - Which weight is the ranking most sensitive to? (worth tuning)
  - Is the current default sitting in the optimal region, or far from it?
  - Does any weight have a monotone benefit/penalty that suggests a structural
    problem (e.g. recency_scale near-zero = recency inert)?

Notes:
  - Sweeps run in ``override`` mode: ONE profile applied to ALL intents.
    Structural intents (COMPARATIVE / TIMELINE) are inert to weights, so they
    contribute their unchanged ordering — consistent with how a global profile
    change would behave in production.
  - Baseline here is the per-intent profile (reproduced at 0.6336 nDCG). The
    "flat default Profile()" point in each sweep is NOT the baseline; we report
    the true baseline separately for comparison.

Run:
    uv run python docs/eval/calibration/sensitivity.py
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rerank import (  # noqa: E402
    BASELINE_PROFILES,
    CALIB_DIR,
    Profile,
    evaluate_ranking,
    load_grades,
    load_queries,
    load_signals,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("calibration.sensitivity")


# Baseline-as-flat-profile is ambiguous (different intents use different
# profiles), so for sensitivity we anchor on a single reference profile and vary
# one axis at a time. We use the ENTITY_OVERVIEW default (the most common and the
# upstream ScoringProfile() default) as the reference.
REF = Profile()  # entity=10, dense=8, event_type=3, bm25_w=0.5, bm25_cap=3, recency=1

# (field, sweep values, label)
SWEEPS: list[tuple[str, list[float], str]] = [
    ("entity_bonus", [0, 2, 4, 6, 8, 10, 12, 15, 20], "entity match bonus (binary)"),
    ("dense_weight", [0, 2, 4, 6, 8, 10, 12, 16], "dense cosine weight"),
    ("event_type_bonus", [0, 1, 2, 3, 5, 8], "event-type match bonus"),
    ("bm25_weight", [0, 0.2, 0.5, 0.8, 1.0, 1.5], "BM25 multiplier"),
    ("bm25_cap", [0, 1, 2, 3, 4, 6, 10], "BM25 cap"),
    ("recency_scale", [0, 1, 10, 100, 1000, 10000], "recency scale factor"),
]


def main() -> None:
    queries = load_queries()
    signals = load_signals()
    grades = load_grades()

    # Baseline (per-intent) for reference.
    base_overall, _, _ = evaluate_ranking(signals, grades, queries, override=None)
    base_ndcg = base_overall.ndcg10
    print("=" * 78)
    print("SINGLE-VARIABLE SENSITIVITY (override profile = REF, vary one field)")
    print(f"REF profile: {REF}")
    print(f"Baseline (per-intent profiles): nDCG@10={base_ndcg:.4f}  "
          f"R@20={base_overall.recall20:.4f}  P@5={base_overall.precision5:.4f}  "
          f"zero%={base_overall.zero_hit_rate * 100:.1f}")
    print("=" * 78)

    all_results: dict[str, list[dict]] = {}
    for field, values, label in SWEEPS:
        print(f"\n--- {field}  ({label}) ---")
        header = (
            f"  {field:>14} | {'nDCG@10':>8} {'Δbase':>7} {'R@20':>7} "
            f"{'P@5':>6} {'zero%':>6} {'MRR':>6}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        rows = []
        for v in values:
            p = replace(REF, **{field: v})
            overall, _, _ = evaluate_ranking(signals, grades, queries, override=p)
            row = {
                "value": v,
                "ndcg10": round(overall.ndcg10, 4),
                "delta_base": round(overall.ndcg10 - base_ndcg, 4),
                "recall20": round(overall.recall20, 4),
                "precision5": round(overall.precision5, 4),
                "zero_hit_rate": round(overall.zero_hit_rate, 4),
                "mrr10": round(overall.mrr10, 4),
            }
            rows.append(row)
            print(
                f"  {v:>14} | {overall.ndcg10:>8.4f} "
                f"{(overall.ndcg10 - base_ndcg):>+7.4f} {overall.recall20:>7.4f} "
                f"{overall.precision5:>6.4f} {overall.zero_hit_rate * 100:>5.1f}% "
                f"{overall.mrr10:>6.4f}"
            )
        all_results[field] = rows

        # Quick read: best nDCG and its value.
        best = max(rows, key=lambda r: r["ndcg10"])
        ref_row = next((r for r in rows if r["value"] == getattr(REF, field)), None)
        print(f"  -> best nDCG {best['ndcg10']:.4f} at {field}={best['value']} "
              f"(REF {field}={getattr(REF, field)} -> "
              f"{ref_row['ndcg10'] if ref_row else 'n/a'})")

    out = CALIB_DIR / "sensitivity.sweep.json"
    out.write_text(
        json.dumps(
            {
                "baseline_ndcg10": round(base_ndcg, 4),
                "ref_profile": REF.__dict__,
                "sweeps": all_results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Wrote %s", out.name)


if __name__ == "__main__":
    main()
