"""Pool-stable re-ranking engine for ScoringProfile weight calibration.

Core idea
---------
The scoring formula in ``src/retrieval/knowledge_search.py:_score_final_hit`` is
*linear* in the per-KU signals. So given each candidate's raw signals
(``bm25_raw``, ``dense_raw``, ``entity_hit``, ``event_type_hit``, ``anchor_ts``),
the final score under ANY ``ScoringProfile`` is a closed-form expression. We can
therefore re-rank the already-judged candidate pool under different weights and
recompute IR metrics — with **zero LLM calls** — by reusing ``v1_labels.json``.

Pool-stable approximation
-------------------------
We do NOT re-run recall; the pool of judged ku_ids per query is fixed (taken
from the baseline retrieval run). Only the ORDER changes. This isolates
*ranking quality* (nDCG/MRR/P@k), which is exactly what the pooled-IDCG nDCG
measures. Recall@20 denominators stay stable because we pass the full judged
``grades`` dict. The trade-off (we ignore that different weights would recall a
different candidate set) is documented in REPORT.md and re-checked by a real
``run_eval`` pass after any weight change lands.

This module is imported by all calibration scripts; it has no side effects.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("calibration")

# --- repo path bootstrap so we can import src.* and docs.eval.* -------------
EVAL_DIR = Path(__file__).resolve().parents[1]           # docs/eval
REPO_ROOT = EVAL_DIR.parents[1]                          # repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CALIB_DIR = EVAL_DIR / "calibration"
SIGNALS_FILE = CALIB_DIR / "component_signals.json"
LABELS_FILE = EVAL_DIR / "golden_labels" / "v1_labels.json"
QUERIES_FILE = EVAL_DIR / "queries-v1.json"
SNAPSHOT_DB = EVAL_DIR / "eval_snapshot.db"

# Mirror of src/retrieval/knowledge_search.py:873 divisor (recency_scale is 1.0).
_RECENCY_DIVISOR = 10_000_000_000_000  # 1e13
_MAX_PER_CLUSTER = 3  # _diversify_by_cluster default


@dataclass(frozen=True)
class Profile:
    """Local mirror of src.retrieval.scoring.ScoringProfile.

    We keep an independent copy so calibration never depends on src/ at import
    time and so we can construct experimental profiles freely. The field names
    match the upstream dataclass 1:1.
    """

    entity_bonus: float = 10.0
    dense_weight: float = 8.0
    event_type_bonus: float = 3.0
    bm25_weight: float = 0.5
    bm25_cap: float = 3.0
    recency_scale: float = 1.0


# Baseline per-intent profiles — MUST match src/retrieval/scoring.py:33-56.
BASELINE_PROFILES: dict[str, Profile] = {
    "ENTITY_OVERVIEW": Profile(),
    "TOPIC_RESEARCH": Profile(
        entity_bonus=6.0, dense_weight=8.0, event_type_bonus=2.0,
        bm25_weight=0.8, bm25_cap=4.0,
    ),
    "EVENT_ANALYSIS": Profile(
        entity_bonus=8.0, dense_weight=7.0, event_type_bonus=5.0,
        bm25_weight=0.6, bm25_cap=3.5,
    ),
    "RELATIONSHIP_QUERY": Profile(
        entity_bonus=10.0, dense_weight=7.0, event_type_bonus=3.0,
        bm25_weight=0.5, bm25_cap=3.0, recency_scale=1.0,
    ),
    # COMPARATIVE_ANALYSIS / ENTITY_TIMELINE: no profile entry upstream (they
    # use structural ordering, not score). We carry defaults for completeness
    # but ranking is a no-op for them — see rerank_query().
}


# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------

@dataclass
class KuSignal:
    """Raw, weight-independent signals for one (query, ku_id) candidate."""

    ku_id: str
    bm25_raw: float          # FTS5 bm25() value (negative) or sentinel 0.0
    dense_raw: float         # cosine similarity [0,1] (0 if absent)
    entity_hit: bool         # entity_bonus would fire
    event_type_hit: bool     # event_type_bonus would fire
    anchor_ts: float         # event_time/published_at epoch seconds
    cluster_id: str | None   # for diversification


def score_ku(sig: KuSignal, p: Profile) -> float:
    """Re-derive final_score for a candidate under profile ``p``.

    This is a faithful, line-by-line mirror of
    ``knowledge_search.py:_score_final_hit`` (lines 846-877). Keep in sync.
    """
    final = 0.0
    if sig.entity_hit:
        final += p.entity_bonus
    if sig.dense_raw > 0:
        final += sig.dense_raw * p.dense_weight
    if sig.event_type_hit:
        final += p.event_type_bonus
    if sig.bm25_raw < 0:
        final += min(-sig.bm25_raw * p.bm25_weight, p.bm25_cap)
    final += (sig.anchor_ts / _RECENCY_DIVISOR) * p.recency_scale
    return final


def _diversify(
    ranked: list[tuple[float, KuSignal]],
    max_per_cluster: int = _MAX_PER_CLUSTER,
) -> list[tuple[float, KuSignal]]:
    """Mirror of _diversify_by_cluster (drops cluster>cap items, preserves order)."""
    counts: dict[str | None, int] = {}
    out: list[tuple[float, KuSignal]] = []
    for score, sig in ranked:
        cid = sig.cluster_id
        if cid is not None and counts.get(cid, 0) >= max_per_cluster:
            continue
        counts[cid] = counts.get(cid, 0) + 1
        out.append((score, sig))
    return out


def rerank_query(
    signals: list[KuSignal],
    p: Profile,
    *,
    structural_order: bool = False,
    top_k: int = 100,
) -> list[str]:
    """Re-rank a query's candidate pool under profile ``p``; return ordered ku_ids.

    Reproduces the full generic-path pipeline:
        sort by (score, anchor_ts, ku_id) desc  ->  _diversify  ->  [:top_k]

    ``structural_order=True`` means the intent's ranking is NOT score-driven
    (COMPARATIVE round-robin / TIMELINE bucketing): we return the original
    pool order untouched, because changing weights cannot affect those orderings.
    """
    if structural_order:
        return [s.ku_id for s in signals[:top_k]]

    scored = [(score_ku(s, p), s) for s in signals]
    scored.sort(key=lambda t: (t[0], t[1].anchor_ts, t[1].ku_id), reverse=True)
    ranked = _diversify(scored)
    return [s.ku_id for _, s in ranked[:top_k]]


# ---------------------------------------------------------------------------
# Profile resolution (global vs per-intent)
# ---------------------------------------------------------------------------

# Intents whose ordering is structural, not score-driven → weights are inert.
STRUCTURAL_INTENTS = {"COMPARATIVE_ANALYSIS", "ENTITY_TIMELINE"}


def profile_for(intent: str, *, override: Profile | None) -> Profile:
    """Resolve the profile to apply for an intent.

    - If ``override`` is given, it is used for ALL intents (single-profile
      calibration mode).
    - Otherwise the baseline per-intent profile is used (or the default
      ``Profile()`` for intents without an explicit entry).
    """
    if override is not None:
        return override
    return BASELINE_PROFILES.get(intent, Profile())


# ---------------------------------------------------------------------------
# Signal file I/O
# ---------------------------------------------------------------------------

def load_queries() -> list[dict]:
    doc = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    return doc.get("queries", [])


def load_signals() -> dict[str, list[KuSignal]]:
    """Load cached per-query signals. Raises if collect_signals hasn't run."""
    if not SIGNALS_FILE.exists():
        raise FileNotFoundError(
            f"{SIGNALS_FILE.name} not found — run "
            "`uv run python docs/eval/calibration/collect_signals.py` first."
        )
    raw = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    out: dict[str, list[KuSignal]] = {}
    for qid, items in raw.items():
        out[qid] = [
            KuSignal(
                ku_id=it["ku_id"],
                bm25_raw=it["bm25_raw"],
                dense_raw=it["dense_raw"],
                entity_hit=it["entity_hit"],
                event_type_hit=it["event_type_hit"],
                anchor_ts=it["anchor_ts"],
                cluster_id=it.get("cluster_id"),
            )
            for it in items
        ]
    return out


def load_grades() -> dict[str, dict[str, int]]:
    """Load judge labels, grouped by query_id.

    Mirrors docs.eval.scripts.judge.LabelStore.load but returns a plain
    ``{qid: {ku_id: grade}}`` mapping for the cached judge model.
    """
    raw = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    out: dict[str, dict[str, int]] = {}
    for item in raw.get("labels", []):
        qid = item["query_id"]
        out.setdefault(qid, {})[item["ku_id"]] = int(item["grade"])
    return out


# ---------------------------------------------------------------------------
# Metrics (imported from docs.eval.scripts.metrics)
# ---------------------------------------------------------------------------

def _eval_metrics():
    from docs.eval.scripts.metrics import (  # type: ignore[import-not-found]
        aggregate,
        aggregate_by_category,
        compute_query_metrics,
    )
    return aggregate, aggregate_by_category, compute_query_metrics


def evaluate_ranking(
    signals_by_q: dict[str, list[KuSignal]],
    grades_by_q: dict[str, dict[str, int]],
    queries: list[dict],
    *,
    override: Profile | None = None,
    top_k: int = 100,
):
    """Re-rank every query under the given profile mode and compute metrics.

    Returns ``(overall, by_category, per_query)`` exactly like
    ``docs.eval.scripts.run_eval.evaluate`` so reports are directly comparable.

    Queries are taken from the golden set; queries with empty signal pools are
    still counted (as zero-hit) to match the baseline macro-average (28 queries).
    """
    aggregate, aggregate_by_category, compute_query_metrics = _eval_metrics()
    per_query = []
    for q in queries:
        qid = q["id"]
        intent = q["intent"]
        signals = signals_by_q.get(qid, [])
        grades = grades_by_q.get(qid, {})
        structural = intent in STRUCTURAL_INTENTS
        p = profile_for(intent, override=override)
        ranked_ids = rerank_query(
            signals, p, structural_order=structural, top_k=top_k
        )
        per_query.append(
            compute_query_metrics(qid, q["category"], ranked_ids, grades)
        )
    overall = aggregate(per_query)
    by_cat = aggregate_by_category(per_query)
    return overall, by_cat, per_query
