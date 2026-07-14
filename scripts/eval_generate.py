"""
黄金评估数据集生成器。

从现有知识库采样 KU → LLM 生成候选查询 → 跑检索管线 → 输出 JSON。

用法:
    uv run python scripts/eval_generate.py [--limit N] [--seed 42] [--top-k 20]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from collections import Counter

from anthropic.types import Message, ToolUseBlock

# ── 项目导入 ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.entities import Entity, EntityRepository
from src.event_merging import EventClusterRepository
from src.knowledge_base import KnowledgeUnit, KnowledgeUnitRepository
from src.llm import create_offline_llm_client, get_offline_max_tokens
from src.orchestration import run_pipeline
from src.schemas.query import IntentType, make_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── LLM 查询生成工具 schema ──────────────────────────────

QUERY_GEN_TOOL_SCHEMA: dict[str, Any] = {
    "name": "generate_search_queries",
    "description": "从知识单元生成模拟金融分析师可能提出的检索查询",
    "input_schema": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "query_text": {
                            "type": "string",
                            "description": "分析师可能输入的自然语言查询",
                        },
                        "query_type": {
                            "type": "string",
                            "enum": [
                                "entity_only",
                                "entity_time",
                                "entity_event_type",
                                "multi_entity",
                                "broad_topic",
                            ],
                        },
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "查询针对的实体名称",
                        },
                        "time_range": {
                            "type": ["object", "null"],
                            "properties": {
                                "start": {"type": "string"},
                                "end": {"type": "string"},
                            },
                        },
                        "event_types": {
                            "type": ["array", "null"],
                            "items": {"type": "string"},
                        },
                        "difficulty": {
                            "type": "string",
                            "enum": ["easy", "medium", "hard"],
                        },
                    },
                    "required": ["query_text", "query_type", "entities", "difficulty"],
                },
                "minItems": 3,
                "maxItems": 5,
            }
        },
        "required": ["queries"],
    },
}

SYSTEM_PROMPT = """你是一名金融检索评估专家。你的任务是从给定的 KnowledgeUnit 生成多样化的检索查询，
模拟真实金融分析师可能会向知识检索系统提出的问题。

# 生成规则
1. 每个查询都必须能检索回当前 KU 作为相关结果
2. 查询类型分布应尽量均匀覆盖以下五类：
   - entity_only: 仅用实体名称搜索（如"小米集团"）
   - entity_time: 实体 + 时间范围（如"宁德时代 2026年4月的事件"）
   - entity_event_type: 实体 + 事件类型（如"恒大集团 债务违约"）
   - multi_entity: 多实体查询（如"宁德时代和比亚迪的对比"）
   - broad_topic: 广泛主题查询（如"新能源汽车行业动态"）
3. 难度分布应包含 easy/medium/hard：
   - easy: 直接实体名称匹配即可召回
   - medium: 需要同义词扩展或精确时间范围
   - hard: 需要多跳推理或跨实体关联
4. query_text 必须是自然的中文，符合金融分析师的表达习惯
5. 如果 KU 的实体不足 2 个，跳过 multi_entity 类型
6. entities 字段只填写 KU 中标注的标准实体（Standard Entities），不要把产品类别、描述性词汇等非实体当作查询实体
7. time_range 格式: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} 或 null
8. event_types 必须从以下标准值中选择，或设为 null："""


def _build_system_prompt() -> str:
    """Append canonical UnitType values to SYSTEM_PROMPT so the LLM uses them."""
    from src.schemas.enums import UnitType
    valid_types = [t.value for t in UnitType]
    return SYSTEM_PROMPT + "\n   " + ", ".join(valid_types)


# ── 分层采样 ──────────────────────────────────────────────

def _type_family(unit_type: str) -> str:
    """Map unit_type to its canonical family name."""
    from src.schemas.enums import normalize_unit_type

    return normalize_unit_type(unit_type).value


def stratified_sample_kus(
    kus: list[KnowledgeUnit],
    target_count: int = 80,
    seed: int = 42,
) -> list[KnowledgeUnit]:
    """按 unit_kind + type_family + 实体多样性分层采样。

    优先采样有已解析实体（entity_id 非空）的 KU。
    """
    rng = random.Random(seed)

    # 过滤：只保留至少有 1 个已解析实体的 KU
    eligible = [ku for ku in kus if any(e.entity_id for e in ku.entities)]
    if len(eligible) < target_count:
        # 不足时回退到全量
        eligible = kus

    # 分组
    groups: dict[str, list[KnowledgeUnit]] = {}
    for ku in eligible:
        key = f"{ku.unit_kind}|{_type_family(ku.unit_type)}"
        groups.setdefault(key, []).append(ku)

    # 按比例分配，每组至少 1 个
    total = len(eligible)
    allocation: dict[str, int] = {}
    remaining = target_count
    for key, group in groups.items():
        alloc = max(1, round(len(group) / total * target_count))
        allocation[key] = min(alloc, len(group))
        remaining -= allocation[key]

    # 补足不足的名额
    if remaining > 0:
        large_keys = sorted(groups.keys(), key=lambda k: len(groups[k]), reverse=True)
        for key in large_keys:
            if remaining <= 0:
                break
            can_add = len(groups[key]) - allocation[key]
            add = min(remaining, max(0, can_add))
            allocation[key] += add
            remaining -= add

    # 采样
    sampled: list[KnowledgeUnit] = []
    for key, group in groups.items():
        alloc = allocation.get(key, 0)
        if alloc > 0:
            sampled.extend(rng.sample(group, min(alloc, len(group))))

    # 确保实体多样性：至少 20 个不同实体
    covered_entities: set[str] = set()
    for ku in sampled:
        for entity in ku.entities:
            if entity.entity_id:
                covered_entities.add(entity.entity_id)

    if len(covered_entities) < 20:
        entity_coverage: dict[str, int] = Counter()
        for ku in eligible:
            for entity in ku.entities:
                if entity.entity_id:
                    entity_coverage[entity.entity_id] += 1
        missing_entities = [
            eid for eid in entity_coverage
            if eid not in covered_entities
        ]
        rng.shuffle(missing_entities)
        for eid in missing_entities:
            if len(covered_entities) >= 20:
                break
            for ku in eligible:
                if ku.ku_id in {s.ku_id for s in sampled}:
                    continue
                if any(e.entity_id == eid for e in ku.entities):
                    sampled.append(ku)
                    covered_entities.add(eid)
                    break

    rng.shuffle(sampled)
    return sampled[:target_count]


# ── LLM 查询生成 ──────────────────────────────────────────

def _build_ku_prompt(ku: KnowledgeUnit, entity_names: list[str]) -> str:
    """构建 LLM 输入 prompt。"""
    event_time = ku.time.event_time.isoformat() if ku.time.event_time else "未知"
    published = ku.time.published_at.isoformat()

    return f"""请根据以下知识单元生成 3-5 个检索查询。

## 知识单元
- 类型: {ku.unit_kind} / {ku.unit_type}
- 摘要: {ku.summary}
- 标准实体: {', '.join(entity_names) if entity_names else '无'}
- 事件时间: {event_time}
- 发布时间: {published}
- 标签: {', '.join(ku.tags) if ku.tags else '无'}

## 重要约束
- entities 字段只能使用上面列出的标准实体名称
- multi_entity 类型只在该 KU 有 2 个及以上标准实体时使用
- 不要把描述性词汇（如"风险"、"增长"）当作 entity"""


def generate_queries_for_ku(
    ku: KnowledgeUnit,
    entity_names: list[str],
    client: Any,
    model: str,
    max_retries: int = 2,
) -> list[dict[str, Any]]:
    """为单个 KU 调用 LLM 生成候选查询。"""
    prompt = _build_ku_prompt(ku, entity_names)
    system_prompt = _build_system_prompt()
    max_tokens = get_offline_max_tokens()

    for attempt in range(max_retries + 1):
        try:
            response: Message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=[QUERY_GEN_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "generate_search_queries"},
                messages=[{"role": "user", "content": prompt}],
            )
            for block in response.content:
                if isinstance(block, ToolUseBlock) and block.name == "generate_search_queries":
                    payload = block.input
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    queries_raw = payload.get("queries", [])
                    return [dict(q) for q in queries_raw]  # type: ignore[arg-type]
            raise ValueError("No tool use block in response")
        except (ValueError, json.JSONDecodeError) as exc:
            if attempt < max_retries:
                logger.warning("查询生成重试 %d/%d: %s", attempt + 1, max_retries + 1, exc)
                time.sleep(0.5 * (attempt + 1))
            else:
                logger.error("查询生成失败 ku=%s: %s", ku.ku_id, exc)
                return []
    return []


# ── 检索执行 ──────────────────────────────────────────────

_INTENT_MAP = {
    "entity_only": IntentType.ENTITY_OVERVIEW,
    "entity_time": IntentType.ENTITY_TIMELINE,
    "entity_event_type": IntentType.EVENT_ANALYSIS,
    "multi_entity": IntentType.COMPARATIVE_ANALYSIS,
    "broad_topic": IntentType.TOPIC_RESEARCH,
}


def run_retrieval_for_query(
    gen_query: dict[str, Any],
    top_k: int = 20,
    graph_enabled: bool = False,
) -> dict[str, Any]:
    """对单个生成的查询跑检索管线。"""
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

    intent = _INTENT_MAP.get(query_type, IntentType.ENTITY_OVERVIEW)

    structured_query = make_query(
        entities=entities,
        intent=intent,
        time_range=time_range,
        event_types=event_types,
    )

    result = run_pipeline(
        structured_query=structured_query,
        graph_enabled=graph_enabled,
        top_k=top_k,
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


# ── 主流程 ────────────────────────────────────────────────

def _generate_rule_queries(
    ku: KnowledgeUnit,
    entity_names: list[str],
) -> list[dict[str, Any]]:
    """Generate queries directly from KU data without LLM.

    Produces predictable queries that map to the retrieval system's capabilities.
    """
    queries: list[dict[str, Any]] = []
    event_time = ku.time.event_time
    published = ku.time.published_at
    unit_type = ku.unit_type

    if not entity_names:
        return queries

    primary_entity = entity_names[0]

    # 1. entity_only: just the primary entity name
    queries.append({
        "query_text": primary_entity,
        "query_type": "entity_only",
        "difficulty": "easy",
        "entities": [primary_entity],
        "time_range": None,
        "event_types": None,
    })

    # 2. entity_time: entity + time range around event
    if event_time:
        from datetime import timedelta
        start = (event_time - timedelta(days=30)).strftime("%Y-%m-%d")
        end = (event_time + timedelta(days=7)).strftime("%Y-%m-%d")
        queries.append({
            "query_text": f"{primary_entity} {event_time.strftime('%Y年%m月')}",
            "query_type": "entity_time",
            "difficulty": "medium",
            "entities": [primary_entity],
            "time_range": {"start": start, "end": end},
            "event_types": None,
        })

    # 3. entity_event_type: entity + canonical unit_type
    if unit_type and unit_type != "other":
        queries.append({
            "query_text": f"{primary_entity} {unit_type}",
            "query_type": "entity_event_type",
            "difficulty": "medium",
            "entities": [primary_entity],
            "time_range": None,
            "event_types": [unit_type],
        })

    # 4. multi_entity: only if 2+ resolved entities
    if len(entity_names) >= 2:
        queries.append({
            "query_text": f"{entity_names[0]}和{entity_names[1]}",
            "query_type": "multi_entity",
            "difficulty": "medium",
            "entities": entity_names[:2],
            "time_range": None,
            "event_types": None,
        })

    # 5. broad_topic: entity + summary keywords
    if ku.tags:
        queries.append({
            "query_text": f"{primary_entity} {' '.join(ku.tags[:3])}",
            "query_type": "broad_topic",
            "difficulty": "hard",
            "entities": [primary_entity],
            "time_range": None,
            "event_types": None,
        })

    return queries


def build_golden_dataset(
    db_path: str = "data/news.db",
    target_kus: int = 80,
    seed: int = 42,
    graph_enabled: bool = False,
    top_k: int = 20,
    limit: int | None = None,
    output_path: str = "eval/golden_dataset_v1.json",
    rule_based: bool = False,
) -> dict[str, Any]:
    """采样 KU → 生成查询 → 跑检索 → 输出 JSON。"""
    logger.info("加载知识库: %s", db_path)

    ku_repo = KnowledgeUnitRepository(db_path)
    entity_repo = EntityRepository(db_path)

    all_kus = ku_repo.get_all()
    all_entities = entity_repo.get_all()
    entity_map = {e.entity_id: e for e in all_entities}

    logger.info("知识库: %d KU, %d Entity", len(all_kus), len(all_entities))

    # 采样
    sample_size = limit or target_kus
    sampled = stratified_sample_kus(all_kus, target_count=sample_size, seed=seed)
    logger.info("采样 %d KU (seed=%d)", len(sampled), seed)

    # LLM 初始化 (only if not rule-based)
    client = None
    model = None
    if not rule_based:
        client, model = create_offline_llm_client()
        logger.info("LLM client ready: model=%s", model)

    items: list[dict[str, Any]] = []
    total_queries = 0

    for idx, ku in enumerate(sampled):
        ku_entity_names = []
        for entity_ref in ku.entities:
            if entity_ref.entity_id and entity_ref.entity_id in entity_map:
                ku_entity_names.append(entity_map[entity_ref.entity_id].canonical_name)
            else:
                ku_entity_names.append(entity_ref.mention)

        # 生成查询
        if rule_based:
            gen_queries = _generate_rule_queries(ku, ku_entity_names)
        else:
            assert model is not None  # rule_based=False 时已在上方初始化
            gen_queries = generate_queries_for_ku(ku, ku_entity_names, client, model)
        if not gen_queries:
            logger.warning("跳过 ku=%s: 无法生成查询", ku.ku_id)
            continue

        item_queries: list[dict[str, Any]] = []
        for gen_q in gen_queries:
            # 过滤：multi_entity 查询的实体必须是标准实体
            if gen_q.get("query_type") == "multi_entity":
                q_entities = gen_q.get("entities", [])
                valid = [e for e in q_entities if e in ku_entity_names]
                if len(valid) < 2:
                    logger.debug(
                        "跳过 multi_entity 查询: 实体不足 2 个标准实体 (got %s, valid %s)",
                        q_entities, valid,
                    )
                    continue
                gen_q["entities"] = valid

            total_queries += 1

            # 跑检索
            try:
                retrieval = run_retrieval_for_query(gen_q, top_k=top_k, graph_enabled=graph_enabled)
            except Exception as exc:
                logger.error("检索失败: %s", exc)
                retrieval = {
                    "top_ku_ids": [],
                    "scores": {},
                    "total_count": 0,
                    "retrieval_mode": "bm25",
                    "bm25_count": 0,
                    "applied_filters": {},
                }

            # 计算 ground truth 排名
            gt_rank = None
            gt_found = False
            for rank, ku_id in enumerate(retrieval["top_ku_ids"], start=1):
                if ku_id == ku.ku_id:
                    gt_rank = rank
                    gt_found = True
                    break

            # 规则预标注
            pre_label = _rule_pre_label(gt_rank, gt_found)

            item_queries.append({
                "query_text": gen_q.get("query_text", ""),
                "query_type": gen_q.get("query_type", "entity_only"),
                "difficulty": gen_q.get("difficulty", "easy"),
                "entities": gen_q.get("entities", []),
                "time_range": gen_q.get("time_range"),
                "event_types": gen_q.get("event_types"),
                "retrieval": {
                    **retrieval,
                    "ground_truth_rank": gt_rank,
                    "ground_truth_found": gt_found,
                },
                "pre_label": pre_label,
                "human_label": None,
                "human_notes": None,
            })

        items.append({
            "item_id": f"item_{idx + 1:03d}",
            "ground_truth_ku": {
                "ku_id": ku.ku_id,
                "unit_kind": ku.unit_kind,
                "unit_type": ku.unit_type,
                "summary": ku.summary,
                "entity_mentions": [e.mention for e in ku.entities],
                "tags": ku.tags,
                "event_time": ku.time.event_time.isoformat() if ku.time.event_time else None,
                "published_at": ku.time.published_at.isoformat(),
            },
            "queries": item_queries,
        })

        logger.info(
            "[%d/%d] ku=%s → %d queries (累计 %d)",
            idx + 1, len(sampled), ku.ku_id, len(item_queries), total_queries,
        )

    dataset = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "metadata": {
            "seed": seed,
            "sampled_kus": len(items),
            "total_queries": total_queries,
            "target_kus": target_kus,
            "db_path": db_path,
            "graph_enabled": graph_enabled,
            "top_k": top_k,
        },
        "items": items,
    }

    # 写入文件
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("输出: %s (%d items, %d queries)", output_path, len(items), total_queries)

    return dataset


def _rule_pre_label(gt_rank: int | None, gt_found: bool) -> int:
    """基于 ground truth 排名的规则预标注。"""
    if not gt_found or gt_rank is None:
        return 0
    if gt_rank <= 3:
        return 3
    if gt_rank <= 10:
        return 2
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="生成黄金评估数据集")
    parser.add_argument("--db", default="data/news.db", help="SQLite 数据库路径")
    parser.add_argument("--target", type=int, default=80, help="目标采样 KU 数量")
    parser.add_argument("--limit", type=int, default=None, help="限制采样数量（测试用）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--top-k", type=int, default=20, help="检索返回数量")
    parser.add_argument("--graph", action="store_true", default=False, help="启用图谱增强")
    parser.add_argument("--output", default="eval/golden_dataset_v1.json", help="输出路径")
    parser.add_argument("--rule-based", action="store_true", default=False, help="使用规则生成查询（不需要 LLM）")
    args = parser.parse_args()

    build_golden_dataset(
        db_path=args.db,
        target_kus=args.target,
        seed=args.seed,
        graph_enabled=args.graph,
        top_k=args.top_k,
        limit=args.limit,
        output_path=args.output,
        rule_based=args.rule_based,
    )


if __name__ == "__main__":
    main()
