"""Diagnostic: inspect signal distributions to explain the sensitivity results.

The sweeps showed entity_bonus / dense_weight / event_type_bonus / recency_scale
all have ZERO effect on ranking while bm25_weight / bm25_cap do. This prints the
signal statistics per query to explain why.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rerank import load_signals  # noqa: E402


def main() -> None:
    signals = load_signals()
    # Aggregate across all queries.
    n_total = 0
    n_entity_hit = 0
    n_dense_pos = 0
    n_bm25_neg = 0
    n_event_type = 0
    dense_vals = []
    bm25_vals = []
    clusters = Counter()

    for qid, sigs in signals.items():
        for s in sigs:
            n_total += 1
            if s.entity_hit:
                n_entity_hit += 1
            if s.dense_raw > 0:
                n_dense_pos += 1
                dense_vals.append(s.dense_raw)
            if s.bm25_raw < 0:
                n_bm25_neg += 1
                bm25_vals.append(s.bm25_raw)
            if s.event_type_hit:
                n_event_type += 1
            clusters[s.cluster_id] += 1

    print(f"Total candidates across {len(signals)} queries: {n_total}")
    print(f"  entity_hit=True     : {n_entity_hit} ({n_entity_hit / n_total:.1%})")
    print(f"  dense_raw > 0       : {n_dense_pos} ({n_dense_pos / n_total:.1%})")
    print(f"  bm25_raw < 0        : {n_bm25_neg} ({n_bm25_neg / n_total:.1%})")
    print(f"  event_type_hit=True : {n_event_type} ({n_event_type / n_total:.1%})")
    print()
    if dense_vals:
        print(f"  dense_raw range: [{min(dense_vals):.4f}, {max(dense_vals):.4f}] "
              f"mean={sum(dense_vals) / len(dense_vals):.4f}")
    else:
        print("  dense_raw: NO positive values — dense retrieval was unavailable.")
    if bm25_vals:
        print(f"  bm25_raw (neg) range: [{min(bm25_vals):.3f}, {max(bm25_vals):.3f}] "
              f"mean={sum(bm25_vals) / len(bm25_vals):.3f}")
    print()

    # Per-query: entity_hit homogeneity check. If entity_hit is uniform within
    # each query (all True or all False), the bonus can't change relative order.
    print("Per-query entity_hit / dense / bm25 pattern (first 12):")
    print(f"  {'qid':<5} {'n':>4} {'ent%':>5} {'dns%':>5} {'bm25%':>5} {'uniform_ent':>11}")
    for qid in sorted(signals)[:12]:
        sigs = signals[qid]
        n = len(sigs)
        eh = sum(1 for s in sigs if s.entity_hit)
        dn = sum(1 for s in sigs if s.dense_raw > 0)
        bm = sum(1 for s in sigs if s.bm25_raw < 0)
        uniform = "ALL" if eh == n else ("NONE" if eh == 0 else "mixed")
        print(f"  {qid:<5} {n:>4} {eh / n if n else 0:>4.0%} "
              f"{dn / n if n else 0:>4.0%} {bm / n if n else 0:>4.0%} {uniform:>11}")

    print()
    # Critical: does entity_hit vary within the top-10 of each query? Because
    # nDCG@10 only cares about the top 10, if all top-10 share the same
    # entity_hit value, the bonus is inert for nDCG purposes.
    print("Within-query variance of entity_hit among top-10 candidates:")
    varying = 0
    for qid, sigs in signals.items():
        top = sigs[:10]
        hits = {s.entity_hit for s in top}
        if len(hits) > 1:
            varying += 1
    print(f"  {varying}/{len(signals)} queries have mixed entity_hit in top-10 "
          "(only these can be reordered by entity_bonus)")


if __name__ == "__main__":
    main()
