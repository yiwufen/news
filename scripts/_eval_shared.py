"""
eval 脚本共享逻辑。

把 ``eval_generate.py`` 的检索重放逻辑（query 构造 → run_pipeline → top_ku_ids）
与 ``eval_report.py`` 的指标计算，提取到这里供 ``eval_run.py`` 复用，避免重复实现，
同时不改动原有两个脚本的现有行为。

这里只放「纯函数」式的共享件；入口侧的副作用（写文件、打印报告）仍归各自脚本。
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from src.orchestration import run_pipeline
from src.schemas.query import IntentType, make_query

# query_type → IntentType 的映射（与 eval_generate.py 保持一致）
INTENT_MAP: dict[str, IntentType] = {
    "entity_only": IntentType.ENTITY_OVERVIEW,
    "entity_time": IntentType.ENTITY_TIMELINE,
    "entity_event_type": IntentType.EVENT_ANALYSIS,
    "multi_entity": IntentType.COMPARATIVE_ANALYSIS,
    "broad_topic": IntentType.TOPIC_RESEARCH,
}


def build_structured_query(gen_query: dict[str, Any]) -> Any:
    """从 golden 集的一条 query dict 构造 StructuredQuery（无 LLM）。"""
    query_type = gen_query.get("query_type", "entity_only")
    entities = gen_query.get("entities", [])
    time_range_raw = gen_query.get("time_range")
    event_types = gen_query.get("event_types")

    time_range: tuple[str, str] | None = None
    if time_range_raw and isinstance(time_range_raw, dict):
        start = time_range_raw.get("start")
        end = time_range_raw.get("end")
        if start and end:
            time_range = (str(start), str(end))

    intent = INTENT_MAP.get(query_type, IntentType.ENTITY_OVERVIEW)
    return make_query(
        entities=entities,
        intent=intent,
        time_range=time_range,
        event_types=event_types,
    )


def run_retrieval(
    gen_query: dict[str, Any],
    *,
    db_path: str,
    top_k: int = 20,
    graph_enabled: bool = False,
) -> dict[str, Any]:
    """对单条 golden query 跑检索，返回 top_ku_ids / scores / 元信息。

    与 ``eval_generate.run_retrieval_for_query`` 等价，但允许注入 db_path 与
    graph_enabled，使本地 fixture 重跑成为可能。
    """
    structured_query = build_structured_query(gen_query)
    result = run_pipeline(
        structured_query=structured_query,
        graph_enabled=graph_enabled,
        top_k=top_k,
        db_path=db_path,
    )

    top_ku_ids: list[str] = []
    scores: dict[str, float] = {}
    for ku_dict in result.knowledge_units:
        ku_id = ku_dict.get("ku_id", "")
        top_ku_ids.append(ku_id)
        score_info = result.retrieval.hit_scores.get(ku_id, {})
        score_val = score_info.get("score", 0.0) if isinstance(score_info, dict) else 0.0
        scores[ku_id] = float(str(score_val))

    return {
        "top_ku_ids": top_ku_ids,
        "scores": scores,
        "total_count": result.total_count,
        "retrieval_mode": result.retrieval.retrieval_mode,
        "bm25_count": result.retrieval.bm25_count,
        "applied_filters": result.retrieval.applied_filters,
    }


def compute_rank(
    top_ku_ids: list[str], ground_truth_ku_id: str
) -> tuple[int | None, bool]:
    """在 top_ku_ids 中找 ground truth KU 的 1-indexed 排名。

    返回 (rank | None, found)。与 eval_generate.py 的 rank 计算逻辑一致。
    """
    for rank, ku_id in enumerate(top_ku_ids, start=1):
        if ku_id == ground_truth_ku_id:
            return rank, True
    return None, False


# ── 指标计算（与 eval_report.py 等价，接受带 retrieval.ground_truth_rank 的 query 列表） ──


def recall_at_k(queries: list[dict[str, Any]], k: int) -> float:
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
    if not queries:
        return 0.0
    total = 0.0
    for q in queries:
        rank = q["retrieval"]["ground_truth_rank"]
        if rank is not None:
            total += 1.0 / rank
    return total / len(queries)


def _label(q: dict[str, Any]) -> int:
    return (
        q.get("human_label")
        or q.get("llm_label")
        or q.get("pre_label")
        or 0
    )


def ndcg_at_k(queries: list[dict[str, Any]], k: int) -> float:
    if not queries:
        return 0.0
    total = 0.0
    count = 0
    for q in queries:
        label = _label(q)
        rank = q["retrieval"]["ground_truth_rank"]
        if rank is not None and rank <= k:
            dcg = label / math.log2(rank + 1)
        else:
            dcg = 0.0
        idcg = label / math.log2(2)
        if idcg > 0:
            total += dcg / idcg
            count += 1
    return total / count if count > 0 else 0.0


def group_queries_by_type(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """把 items 展开为扁平 query 列表，并按 query_type 分组。每个 query 附带 item_id。"""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for q in item.get("queries", []):
            qtype = q.get("query_type", "unknown")
            groups[qtype].append(q)
    return groups


def all_queries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [q for item in items for q in item.get("queries", [])]
