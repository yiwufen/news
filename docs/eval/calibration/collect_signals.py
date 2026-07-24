"""Step 1 — Collect raw per-KU ranking signals for the eval query set.

Runs ``run_pipeline`` (graph disabled) once per query against the frozen eval
snapshot DB — sqlite + FAISS only, **no LLM calls** — and extracts the
weight-independent raw signals that ``_score_final_hit`` consumes:

    bm25_raw       FTS5 bm25() (negative) or sentinel 0.0 / -1.0
    dense_raw      cosine similarity [0,1] (0 if absent)
    entity_hit     whether entity_bonus fires
    event_type_hit whether event_type_bonus fires
    anchor_ts      event_time/published_at epoch seconds
    cluster_id     for diversification

Output: ``component_signals.json`` — one entry per query, list of signals.
Consumed by reproduce_baseline / sensitivity / grid_search.

Run:
    uv run python docs/eval/calibration/collect_signals.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap repo path for src.* / docs.eval.* imports.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rerank import QUERIES_FILE, SIGNALS_FILE, SNAPSHOT_DB  # noqa: E402

logger = logging.getLogger("calibration.collect")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _anchor_ts(unit: dict) -> float:
    """event_time → published_at → epoch seconds (mirror of _unit_anchor)."""
    t = unit.get("time") or {}
    when = t.get("event_time") or t.get("published_at")
    if not when:
        return datetime.min.replace(tzinfo=timezone.utc).timestamp()
    # KU payloads serialize datetimes as ISO strings.
    if isinstance(when, str):
        try:
            return datetime.fromisoformat(when).timestamp()
        except ValueError:
            return 0.0
    return float(getattr(when, "timestamp", lambda: 0.0)())


def _extract_signals(q: dict, db_path: str, judge_pool_k: int) -> list[dict]:
    """Run retrieval for one query; return raw signals per judged KU."""
    from docs.eval.scripts.run_eval import build_structured_query  # noqa: E402
    from src.orchestration.graph import run_pipeline  # noqa: E402

    structured = build_structured_query(q)
    result = run_pipeline(
        structured_query=structured,
        graph_enabled=False,  # eval measures retrieval quality, not graph
        top_k=judge_pool_k,
        db_path=db_path,
    )

    units = result.knowledge_units
    hit_scores = result.retrieval.hit_scores
    unit_by_id = {u["ku_id"]: u for u in units}

    out: list[dict] = []
    for ku_id, unit in unit_by_id.items():
        meta = hit_scores.get(ku_id, {})
        comp_obj = meta.get("component_scores") if isinstance(meta, dict) else None
        comp: dict = comp_obj if isinstance(comp_obj, dict) else {}
        out.append(
            {
                "ku_id": ku_id,
                # Raw inputs stored upstream; preserves sign/scale.
                "bm25_raw": float(comp.get("bm25_score", 0.0)),
                "dense_raw": float(comp.get("dense_score", 0.0)),
                # Binary trigger keys are present iff the bonus fired.
                "entity_hit": "entity_bonus" in comp,
                "event_type_hit": "event_type_bonus" in comp,
                "anchor_ts": _anchor_ts(unit),
                "cluster_id": unit.get("cluster_id"),
            }
        )
    # Preserve retrieval order (signals[0] is the top-ranked KU) so structural
    # intents (comparative/timeline) can be replayed without re-scoring.
    order = {u["ku_id"]: i for i, u in enumerate(units)}
    out.sort(key=lambda s: order.get(s["ku_id"], 1_000_000))
    return out


def main() -> None:
    if not SNAPSHOT_DB.exists():
        raise FileNotFoundError(
            f"Snapshot DB not found: {SNAPSHOT_DB}. Run "
            "`uv run python docs/eval/scripts/snapshot.py` first."
        )
    queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    logger.info("Collecting signals for %d queries from %s", len(queries), SNAPSHOT_DB)

    judge_pool_k = 100  # matches docs/eval baseline (judge_pool_k default)
    signals: dict[str, list[dict]] = {}
    for i, q in enumerate(queries, 1):
        qid = q["id"]
        try:
            sigs = _extract_signals(q, str(SNAPSHOT_DB), judge_pool_k)
        except Exception:
            logger.exception("[%d/%d] %s — retrieval failed", i, len(queries), qid)
            sigs = []
        signals[qid] = sigs
        logger.info(
            "[%d/%d] %s — %d candidates (intent=%s)",
            i, len(queries), qid, len(sigs), q["intent"],
        )

    SIGNALS_FILE.write_text(
        json.dumps(signals, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(len(v) for v in signals.values())
    logger.info(
        "Wrote %s — %d queries, %d total signals", SIGNALS_FILE.name,
        len(signals), total,
    )


if __name__ == "__main__":
    main()
