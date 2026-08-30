"""Retrieval quality metrics computed from judge-labeled results.

Each query produces an ordered list of retrieved KU ids (the ranking) and a
mapping ``ku_id -> grade`` (0/1/2) from the LLM judge. This module turns that
into standard IR metrics:

    nDCG@k      graded gain, position-discounted, normalized by ideal ordering
    Recall@k    share of pool-relevant (grade>=1) KUs found in top-k
    MRR@k       reciprocal rank of the first relevant (grade>=1) hit
    Precision@k share of top-k that are relevant (grade>=1)
    zero-hit    True if NO retrieved KU is relevant (grade>=1)

Graded relevance mapping:
    grade 2 (relevant)   -> gain 2  (used for nDCG)
    grade 1 (partial)    -> gain 1
    grade 0 (irrelevant) -> gain 0

For binary metrics (Recall/MRR/Precision), grade>=1 counts as a hit.

Recall denominator — TREC-style pooled judging:
    The judge labels a POOL of candidates (top-``judge_pool_k``, default 100),
    not just the final top-k ranking. ``n_relevant_total`` is the count of
    grade>=1 KUs across this whole judged pool, and serves as the shared
    denominator for every Recall@k. This is the standard TREC-pool approximation
    of corpus-wide recall: it avoids the old self-referential denominator
    (top-k hits / top-k relevant) that made Recall@k a near-tautology.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class QueryMetrics:
    query_id: str
    category: str
    n_retrieved: int
    n_relevant_total: int  # grade>=1 across the whole JUDGED POOL (denominator for Recall@k)
    n_relevant_grade2: int  # grade==2 across the whole judged pool
    ndcg10: float
    recall5: float
    recall20: float
    mrr10: float
    precision5: float
    zero_hit: bool
    retrieval_path: str = "unknown"  # actual route taken (entity_events / hybrid / ...)

    def to_dict(self) -> dict:
        return {
            "query_id": self.query_id,
            "category": self.category,
            "n_retrieved": self.n_retrieved,
            "n_relevant_total": self.n_relevant_total,
            "n_relevant_grade2": self.n_relevant_grade2,
            "ndcg10": round(self.ndcg10, 4),
            "recall5": round(self.recall5, 4),
            "recall20": round(self.recall20, 4),
            "mrr10": round(self.mrr10, 4),
            "precision5": round(self.precision5, 4),
            "zero_hit": self.zero_hit,
            "retrieval_path": self.retrieval_path,
        }


@dataclass
class AggregateMetrics:
    n_queries: int = 0
    ndcg10: float = 0.0
    recall5: float = 0.0
    recall20: float = 0.0
    mrr10: float = 0.0
    precision5: float = 0.0
    zero_hit_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "n_queries": self.n_queries,
            "ndcg10": round(self.ndcg10, 4),
            "recall5": round(self.recall5, 4),
            "recall20": round(self.recall20, 4),
            "mrr10": round(self.mrr10, 4),
            "precision5": round(self.precision5, 4),
            "zero_hit_rate": round(self.zero_hit_rate, 4),
        }


def _dcg(gains: list[int]) -> float:
    """Discounted Cumulative Gain for a gain sequence (position 0-indexed)."""
    total = 0.0
    for i, g in enumerate(gains):
        if g > 0:
            total += g / math.log2(i + 2)  # +2 because rank starts at 1
    return total


def _ndcg_at_k(ranked_grades: list[int], k: int) -> float:
    """nDCG@k for an ordered grade list (already in retrieval order).

    Ideal DCG is computed by sorting grades descending (best first).
    """
    top = ranked_grades[:k]
    dcg = _dcg(top)
    ideal = sorted(ranked_grades, reverse=True)[:k]
    idcg = _dcg(ideal)
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _recall_at_k(ranked_grades: list[int], n_relevant_total: int, k: int) -> float:
    if n_relevant_total == 0:
        return 0.0
    hits = sum(1 for g in ranked_grades[:k] if g >= 1)
    return hits / n_relevant_total


def _mrr_at_k(ranked_grades: list[int], k: int) -> float:
    for i, g in enumerate(ranked_grades[:k]):
        if g >= 1:
            return 1.0 / (i + 1)
    return 0.0


def _precision_at_k(ranked_grades: list[int], k: int) -> float:
    if k == 0:
        return 0.0
    hits = sum(1 for g in ranked_grades[:k] if g >= 1)
    return hits / k


def compute_query_metrics(
    query_id: str,
    category: str,
    ranked_ku_ids: list[str],
    grades: dict[str, int],
    retrieval_path: str = "unknown",
) -> QueryMetrics:
    """Compute all metrics for one query.

    ``ranked_ku_ids`` is the retrieval ordering (best first). ``grades`` maps
    ku_id -> judge grade (0/1/2) across the WHOLE judged pool — it must cover
    every KU in the pool, not just the final top-k ranking, so that the
    Recall@k denominator reflects the pool-relevant count (TREC-style pooling).
    KUs without a grade default to 0.

    ``retrieval_path`` is the route actually taken (KnowledgeSearchResult.
    retrieval_path) — grouping by it separates the entity route and text route
    baselines so changes to one do not dilute the other's regression signal.
    """
    ranked_grades = [grades.get(kid, 0) for kid in ranked_ku_ids]
    # n_relevant_total spans the entire judged pool (all graded KUs), which is
    # the shared Recall@k denominator. It is intentionally NOT derived from the
    # truncated ranked_grades list.
    n_relevant_total = sum(1 for g in grades.values() if g >= 1)
    n_relevant_grade2 = sum(1 for g in grades.values() if g == 2)
    zero_hit = sum(1 for g in ranked_grades if g >= 1) == 0

    return QueryMetrics(
        query_id=query_id,
        category=category,
        n_retrieved=len(ranked_ku_ids),
        n_relevant_total=n_relevant_total,
        n_relevant_grade2=n_relevant_grade2,
        ndcg10=_ndcg_at_k(ranked_grades, 10),
        recall5=_recall_at_k(ranked_grades, n_relevant_total, 5),
        recall20=_recall_at_k(ranked_grades, n_relevant_total, 20),
        mrr10=_mrr_at_k(ranked_grades, 10),
        precision5=_precision_at_k(ranked_grades, 5),
        zero_hit=zero_hit,
        retrieval_path=retrieval_path,
    )


def aggregate(metrics: list[QueryMetrics]) -> AggregateMetrics:
    """Macro-average across queries (mean of per-query metrics)."""
    n = len(metrics)
    if n == 0:
        return AggregateMetrics()
    return AggregateMetrics(
        n_queries=n,
        ndcg10=sum(m.ndcg10 for m in metrics) / n,
        recall5=sum(m.recall5 for m in metrics) / n,
        recall20=sum(m.recall20 for m in metrics) / n,
        mrr10=sum(m.mrr10 for m in metrics) / n,
        precision5=sum(m.precision5 for m in metrics) / n,
        zero_hit_rate=sum(1 for m in metrics if m.zero_hit) / n,
    )


def aggregate_by_category(
    metrics: list[QueryMetrics],
) -> dict[str, AggregateMetrics]:
    """Group by query category and aggregate within each group."""
    groups: dict[str, list[QueryMetrics]] = defaultdict(list)
    for m in metrics:
        groups[m.category].append(m)
    return {cat: aggregate(ms) for cat, ms in groups.items()}


def aggregate_by_path(
    metrics: list[QueryMetrics],
) -> dict[str, AggregateMetrics]:
    """Group by the retrieval route actually taken and aggregate within each group."""
    groups: dict[str, list[QueryMetrics]] = defaultdict(list)
    for m in metrics:
        groups[m.retrieval_path].append(m)
    return {path: aggregate(ms) for path, ms in groups.items()}


def format_report(
    overall: AggregateMetrics,
    by_category: dict[str, AggregateMetrics],
    per_query: list[QueryMetrics],
    by_path: dict[str, AggregateMetrics] | None = None,
) -> str:
    """Render a human-readable text report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("RETRIEVAL EVALUATION REPORT")
    lines.append("=" * 72)
    lines.append("")
    lines.append("Overall (macro-avg over {} queries):".format(overall.n_queries))
    lines.append(
        f"  nDCG@10      : {overall.ndcg10:.4f}   <- primary ranking quality metric"
    )
    lines.append(f"  Recall@5     : {overall.recall5:.4f}")
    lines.append(f"  Recall@20    : {overall.recall20:.4f}")
    lines.append(f"  MRR@10       : {overall.mrr10:.4f}")
    lines.append(f"  Precision@5  : {overall.precision5:.4f}")
    lines.append(f"  zero-hit rate: {overall.zero_hit_rate:.4f}   <- lower is better")
    lines.append("")
    lines.append("By retrieval path (actual route taken):")
    lines.append(
        f"  {'path':<26} {'n':>3} {'nDCG@10':>8} {'Rec@5':>8} {'Rec@20':>8} {'MRR@10':>8} {'P@5':>8} {'zero%':>7}"
    )
    lines.append("  " + "-" * 76)
    for path, agg in sorted((by_path or {}).items()):
        lines.append(
            f"  {path:<26} {agg.n_queries:>3} "
            f"{agg.ndcg10:>8.4f} {agg.recall5:>8.4f} {agg.recall20:>8.4f} "
            f"{agg.mrr10:>8.4f} {agg.precision5:>8.4f} "
            f"{agg.zero_hit_rate * 100:>6.1f}%"
        )
    lines.append("")
    lines.append("By category:")
    lines.append(
        f"  {'category':<26} {'n':>3} {'nDCG@10':>8} {'Rec@5':>8} {'Rec@20':>8} {'MRR@10':>8} {'P@5':>8} {'zero%':>7}"
    )
    lines.append("  " + "-" * 76)
    for cat, agg in sorted(by_category.items()):
        lines.append(
            f"  {cat:<26} {agg.n_queries:>3} "
            f"{agg.ndcg10:>8.4f} {agg.recall5:>8.4f} {agg.recall20:>8.4f} "
            f"{agg.mrr10:>8.4f} {agg.precision5:>8.4f} "
            f"{agg.zero_hit_rate * 100:>6.1f}%"
        )
    lines.append("")
    lines.append("Per query (sorted by nDCG@10 ascending — worst first):")
    lines.append(
        f"  {'id':<5} {'category':<26} {'nRet':>4} {'nRel':>4} {'nDCG':>6} {'R@5':>6} {'R@20':>6} {'MRR':>6} {'P@5':>6}"
    )
    lines.append("  " + "-" * 76)
    for m in sorted(per_query, key=lambda x: x.ndcg10):
        lines.append(
            f"  {m.query_id:<5} {m.category:<26} {m.n_retrieved:>4} "
            f"{m.n_relevant_total:>4} {m.ndcg10:>6.3f} {m.recall5:>6.3f} {m.recall20:>6.3f} "
            f"{m.mrr10:>6.3f} {m.precision5:>6.3f}"
        )
    lines.append("")
    return "\n".join(lines)
