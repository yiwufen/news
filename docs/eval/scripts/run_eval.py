"""End-to-end retrieval evaluation runner.

Pipeline per query::

    queries-v1.json entry
      -> make_query() builds StructuredQuery
      -> run_pipeline(structured_query, db_path=eval_snapshot.db, top_k=judge_pool_k)
      -> collect ordered ku_ids (the judged pool) + payloads
      -> judge.label_query_hits() over the WHOLE pool (cached, incremental)
      -> metrics.compute_query_metrics() — top-k ranking metrics + pool-recall

The judge labels a POOL of ``judge_pool_k`` candidates (default 100), not just
the final ``top_k`` ranking (default 30). Recall@k uses the pool-relevant count
as its denominator (TREC-style pooling), avoiding the self-referential
denominator bug. nDCG/MRR/Precision only depend on the ranking order and are
evaluated at their standard cutoffs via the metrics module.

Outputs:
    - results/<timestamp>_report.json   (machine-readable, full detail)
    - results/<timestamp>_report.txt    (human-readable summary)
    - console summary table

Usage::

    # Full run (creates snapshot if missing, judges all, reports)
    uv run python docs/eval/scripts/run_eval.py

    # Limit to N queries (smoke test the full chain)
    uv run python docs/eval/scripts/run_eval.py --limit 3

    # Rejudge from scratch (ignore cached labels)
    uv run python docs/eval/scripts/run_eval.py --refresh

    # Use a specific snapshot without recreating
    uv run python docs/eval/scripts/run_eval.py --no-snapshot-check
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make the repo root importable when running this file directly.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docs.eval.scripts.judge import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    LabelStore,
    label_query_hits,
)
from docs.eval.scripts.metrics import (  # noqa: E402
    aggregate,
    aggregate_by_category,
    compute_query_metrics,
    format_report,
    QueryMetrics,
)
from docs.eval.scripts.snapshot import (  # noqa: E402
    SNAPSHOT_DB,
    create_snapshot,
    load_meta,
)
from src.orchestration.graph import run_pipeline  # noqa: E402
from src.schemas.query import IntentType, make_query  # noqa: E402

logger = logging.getLogger("eval")

EVAL_DIR = Path(__file__).resolve().parents[1]
QUERIES_FILE = EVAL_DIR / "queries-v1.json"
RESULTS_DIR = EVAL_DIR / "results"


def build_structured_query(q: dict):
    """Translate an eval-set query entry into a StructuredQuery."""
    intent = IntentType(q["intent"])
    return make_query(
        entities=q.get("entities") or [],
        intent=intent,
        time_range=tuple(q["time_range"]) if q.get("time_range") else None,
        event_types=q.get("event_types"),
        hops=q.get("hops", 1),
        target_entity=q.get("target_entity"),
        # Pass the raw query text so topic queries (entities=[]) don't
        # short-circuit on an empty original_query.
        original_query=q.get("query_text"),
    )


def run_one_query(
    q: dict, db_path: str, judge_pool_k: int
) -> tuple[list[str], list[dict], dict]:
    """Run retrieval for one query. Returns (ordered_ku_ids, ku_payloads, retrieval_meta).

    Retrieves ``judge_pool_k`` candidates so the judge can label a wide pool;
    the final top-k ranking depth is applied later inside the metrics module
    (nDCG/MRR/Precision all slice internally). Pool recall uses the full pool
    as its denominator.
    """
    structured = build_structured_query(q)

    # run_pipeline captures stdout internally to filter driver warnings; we
    # just consume the returned PipelineResult.
    result = run_pipeline(
        structured_query=structured,
        graph_enabled=False,  # eval measures retrieval quality, not graph
        top_k=judge_pool_k,
        db_path=db_path,
    )

    units = result.knowledge_units
    ku_ids = [u["ku_id"] for u in units]
    retrieval_meta = {
        "retrieval_mode": result.retrieval.retrieval_mode,
        "bm25_count": result.retrieval.bm25_count,
        "total_count": result.total_count,
        "warnings": result.warnings,
    }
    return ku_ids, units, retrieval_meta


def evaluate(
    queries: list[dict],
    db_path: str,
    judge_pool_k: int,
    judge_model: str,
    store: LabelStore,
    refresh: bool = False,
) -> tuple[dict, list]:
    """Run the full evaluation.

    Returns (result_dict, query_metrics_objects). The metrics objects are
    returned alongside the dict so callers can format reports without
    reconstructing dataclasses from serialized dicts.
    """
    per_query_metrics: list = []
    query_details = []

    for idx, q in enumerate(queries, 1):
        qid = q["id"]
        logger.info("[%d/%d] %s — %s", idx, len(queries), qid, q["query_text"])

        try:
            ku_ids, ku_payloads, retrieval_meta = run_one_query(q, db_path, judge_pool_k)
        except Exception:
            logger.exception("[%s] retrieval failed", qid)
            query_details.append(
                {"query_id": qid, "status": "retrieval_error", "error": "see logs"}
            )
            continue

        if not ku_ids:
            logger.warning("[%s] retrieved 0 KUs", qid)
            m = compute_query_metrics(qid, q["category"], [], {})
            per_query_metrics.append(m)
            query_details.append(
                {
                    "query_id": qid,
                    "query": q,
                    "status": "empty",
                    "retrieval": retrieval_meta,
                    "ranked_ku_ids": [],
                    "grades": {},
                    "metrics": m.to_dict(),
                }
            )
            continue

        # Judge the WHOLE pool (cache-aware; refresh ignores cache by using a
        # fresh store key). Recall@k denominators come from this pool.
        judge_store = LabelStore(q["id"] + "__nocache") if refresh else store
        grades = label_query_hits(q, ku_payloads, judge_store, model=judge_model)
        if judge_store is not store:
            # Merge fresh labels back into the real store so they persist.
            for lb in judge_store.labels.values():
                store.upsert(lb)

        m = compute_query_metrics(qid, q["category"], ku_ids, grades)
        per_query_metrics.append(m)
        query_details.append(
            {
                "query_id": qid,
                "query": q,
                "status": "ok",
                "retrieval": retrieval_meta,
                "ranked_ku_ids": ku_ids,
                "grades": {kid: g for kid, g in grades.items()},
                "metrics": m.to_dict(),
            }
        )
        logger.info(
            "[%s] pool=%d relevant(>=1)=%d grade2=%d nDCG@10=%.3f",
            qid,
            len(ku_ids),
            m.n_relevant_total,
            m.n_relevant_grade2,
            m.ndcg10,
        )

    overall = aggregate(per_query_metrics)
    by_category = aggregate_by_category(per_query_metrics)

    result = {
        "eval_version": "v1",
        "timestamp": datetime.now(UTC).isoformat(),
        "judge_model": judge_model,
        "judge_pool_k": judge_pool_k,
        "db_path": str(Path(db_path).relative_to(REPO_ROOT))
        if REPO_ROOT in Path(db_path).resolve().parents
        else db_path,
        "snapshot_meta": load_meta(),
        "overall": overall.to_dict(),
        "by_category": {k: v.to_dict() for k, v in by_category.items()},
        "per_query": query_details,
        "per_query_metrics": [m.to_dict() for m in per_query_metrics],
    }
    return result, per_query_metrics


def save_report(result: dict, qm_list: list) -> tuple[Path, Path]:
    """Write JSON + text reports. qm_list is the list of QueryMetrics objects."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"{ts}_report.json"
    txt_path = RESULTS_DIR / f"{ts}_report.txt"

    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    txt = format_report(
        overall=aggregate(qm_list),
        by_category=aggregate_by_category(qm_list),
        per_query=qm_list,
    )
    txt += f"\nJudge model: {result['judge_model']}\n"
    txt += f"Eval set: {result['eval_version']}  |  judge_pool_k: {result['judge_pool_k']}\n"
    snap = result.get("snapshot_meta") or {}
    if snap:
        txt += (
            f"Snapshot: KUs={snap.get('ku_count', '?')} "
            f"commit={snap.get('git_commit', '?')[:12]} "
            f"created={snap.get('snapshot_created', '?')[:19]}\n"
        )
    txt_path.write_text(txt, encoding="utf-8")
    return json_path, txt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only run first N queries")
    parser.add_argument(
        "--judge-pool-k",
        type=int,
        default=100,
        help="Number of candidates to retrieve and judge per query (Recall denominator pool). Default 100.",
    )
    parser.add_argument("--refresh", action="store_true", help="Rejudge, ignore cache")
    parser.add_argument(
        "--no-snapshot-check",
        action="store_true",
        help="Skip snapshot existence check (use when DB path set explicitly)",
    )
    parser.add_argument("--db", default=str(SNAPSHOT_DB), help="DB path (default: eval snapshot)")
    parser.add_argument(
        "--queries", default=str(QUERIES_FILE), help="Path to queries JSON"
    )
    parser.add_argument(
        "--judge-model", default=DEFAULT_JUDGE_MODEL, help=f"Judge model (default {DEFAULT_JUDGE_MODEL})"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Ensure snapshot exists
    db_path: str = args.db
    if db_path == str(SNAPSHOT_DB) and not args.no_snapshot_check:
        if not SNAPSHOT_DB.exists():
            logger.info("Creating eval snapshot from data/news.db ...")
            create_snapshot()

    # Load queries
    queries_doc = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    queries = queries_doc["queries"]
    if args.limit:
        queries = queries[: args.limit]
        logger.info("Limited to first %d queries", len(queries))

    # Load label store (cache)
    store = LabelStore.load(queries_doc.get("version", "v1"))

    logger.info(
        "Starting eval: %d queries, judge_pool_k=%d, judge=%s, db=%s",
        len(queries), args.judge_pool_k, args.judge_model, db_path,
    )

    result, qm_list = evaluate(
        queries=queries,
        db_path=db_path,
        judge_pool_k=args.judge_pool_k,
        judge_model=args.judge_model,
        store=store,
        refresh=args.refresh,
    )

    # Persist labels cache
    store.save()

    json_path, txt_path = save_report(result, qm_list)

    print()
    print(
        format_report(
            overall=aggregate(qm_list),
            by_category=aggregate_by_category(qm_list),
            per_query=qm_list,
        )
    )
    print(f"\nReport saved:\n  {json_path}\n  {txt_path}")


if __name__ == "__main__":
    main()
