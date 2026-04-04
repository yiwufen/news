"""
LangGraph 节点函数（V2 版本）

使用 PipelineContext 和 StageOutput 的节点函数。
每个节点返回 StageOutput，由适配器转换为 LangGraph 需要的格式。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.agents.critic import CriticAgent
from src.agents.integrator import IntegratorAgent
from src.agents.master import MasterAgent
from src.agents.worker import WorkerAgent
from src.orchestration.state import PipelineContext, StageOutput
from src.schemas import IntelligenceParticle


def intent_parse_node(ctx: PipelineContext) -> StageOutput:
    """意图解析节点

    将用户自然语言查询解析为结构化查询。
    解析结果直接更新到 ctx.input 中。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含解析结果或错误信息
    """
    from src.intent import IntentClassifier

    start_time = datetime.now()

    if not ctx.input or not ctx.input.raw_query:
        return StageOutput.failure(
            stage_name="intent_parse",
            errors=["无用户查询"],
        )

    try:
        classifier = IntentClassifier()
        structured = classifier.parse(ctx.input.raw_query)

        ctx.input.intent = structured.intent
        ctx.input.entities = structured.entities
        ctx.input.time_range = structured.time_range
        ctx.input.filters = structured.filters

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="intent_parse",
            data={
                "structured_query": structured.to_dict(),
                "confidence": structured.confidence,
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="intent_parse",
            errors=[f"意图解析错误: {str(e)}"],
        )


# =============================================================================
# 检索节点
# =============================================================================


def retrieval_node(ctx: PipelineContext) -> StageOutput:
    """检索节点

    任务驱动模式：优先检索已存储的情报微粒。
    回退机制：若无微粒，检索原始文章。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含检索到的微粒或文章
    """
    from src.retrieval import HybridSearcher, ParticleRetrievalRequest, ParticleSearcher

    start_time = datetime.now()

    # 检查前置条件
    if not ctx.input:
        # 检查是否有直接输入的数据
        articles = ctx.get_articles()
        if articles:
            return StageOutput.ok(
                stage_name="retrieval",
                data={"articles": articles, "source": "direct_input"},
            )
        return StageOutput.failure(
            stage_name="retrieval",
            errors=["无查询输入且无直接输入数据"],
        )

    try:
        # 1. 优先从情报微粒检索
        particle_searcher = ParticleSearcher()

        # 构建检索请求
        from src.intent.models import StructuredQuery

        from src.intent.models import IntentType as IT

        # 处理 intent 可能为 None 的情况
        intent = ctx.input.intent or IT.ENTITY_TIMELINE

        structured_query = StructuredQuery(
            intent=intent,
            entities=ctx.input.entities,
            time_range=ctx.input.time_range,
            filters=ctx.input.filters,
            original_query=ctx.input.raw_query,
        )

        particle_result = particle_searcher.search(
            ParticleRetrievalRequest(
                structured_query=structured_query,
                top_k=50,
            )
        )

        duration = (datetime.now() - start_time).microseconds // 1000

        # 如果找到情报微粒，直接使用
        if not particle_result.is_empty():
            return StageOutput.ok(
                stage_name="retrieval",
                data={
                    "particles": particle_result.particles,
                    "total_count": particle_result.total_count,
                    "source": "particles",
                    "filters_applied": particle_result.filters_applied,
                },
                duration_ms=duration,
            )

        # 2. 回退：检索原始文章
        from src.retrieval import RetrievalRequest

        article_searcher = HybridSearcher()
        article_result = article_searcher.search(
            RetrievalRequest(
                structured_query=structured_query,
                top_k=100,
            )
        )

        return StageOutput.ok(
            stage_name="retrieval",
            data={
                "articles": article_result.articles,
                "total_count": article_result.total_count,
                "source": "articles_fallback",
                "note": "无已存储的情报微粒，回退到原始文章检索",
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="retrieval",
            errors=[f"检索错误: {str(e)}"],
        )


# =============================================================================
# Worker Agent 节点
# =============================================================================


def worker_node(ctx: PipelineContext) -> StageOutput:
    """Worker Agent 节点

    从文章中提取情报微粒。
    仅在以下情况使用：
    1. 持续运行模式：批量处理新闻
    2. 任务驱动模式回退：无已存储情报微粒时实时提取

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含提取的情报微粒
    """
    start_time = datetime.now()

    articles = ctx.get_articles()

    if not articles:
        return StageOutput.failure(
            stage_name="worker",
            errors=["无文章数据"],
        )

    try:
        agent = WorkerAgent()
        particles = agent.extract_from_articles(articles)

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="worker",
            data={
                "particles": particles,
                "count": len(particles),
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="worker",
            errors=[f"Worker Agent 错误: {str(e)}"],
        )


# =============================================================================
# Integrator Agent 节点
# =============================================================================


def integrator_node(ctx: PipelineContext) -> StageOutput:
    """Integrator Agent 节点

    执行实体对齐和图谱同步。
    graph_enabled 判断在 Agent 内部处理。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含同步结果
    """
    start_time = datetime.now()

    particles = ctx.get_particles()

    if not particles:
        return StageOutput.failure(
            stage_name="integrator",
            errors=["无情报微粒数据"],
        )

    try:
        agent = IntegratorAgent(graph_enabled=ctx.graph_enabled)
        result = agent.run(particles)

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="integrator",
            data={
                "entities_created": result.get("entities_created", 0),
                "entities_merged": result.get("entities_merged", 0),
                "edges_created": result.get("edges_created", 0),
                "details": result.get("details", []),
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="integrator",
            errors=[f"Integrator Agent 错误: {str(e)}"],
        )


# =============================================================================
# Master Agent 节点
# =============================================================================


def master_node(ctx: PipelineContext) -> StageOutput:
    """Master Agent 节点

    执行风险穿透分析和报告生成。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含分析报告
    """
    start_time = datetime.now()

    # 获取目标实体
    target_entity = None
    if ctx.input and ctx.input.entities:
        target_entity = ctx.input.entities[0]

    if not target_entity:
        return StageOutput.failure(
            stage_name="master",
            errors=["无目标实体"],
        )

    # 获取情报微粒
    particles = ctx.get_particles()

    if not particles:
        return StageOutput.failure(
            stage_name="master",
            errors=["无情报微粒数据"],
        )

    try:
        agent = MasterAgent(graph_enabled=ctx.graph_enabled)
        report = agent.analyze(
            target_entity=target_entity,
            particles=particles,
        )

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="master",
            data={
                "report": report.to_dict(),
                "risk_level": report.risk_level,
                "risk_score": report.risk_score,
                "target_entity": target_entity,
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="master",
            errors=[f"Master Agent 错误: {str(e)}"],
        )


# =============================================================================
# 时间线节点
# =============================================================================


def timeline_node(ctx: PipelineContext) -> StageOutput:
    """时间线生成节点

    生成实体的历史行为时间线。
    直接使用已检索的情报微粒，无需重新提取。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含时间线数据
    """
    start_time = datetime.now()

    # 获取目标实体
    target_entity = None
    if ctx.input and ctx.input.entities:
        target_entity = ctx.input.entities[0]

    if not target_entity:
        return StageOutput.failure(
            stage_name="timeline",
            errors=["无目标实体"],
        )

    # 获取情报微粒
    particles = ctx.get_particles()

    if not particles:
        return StageOutput.failure(
            stage_name="timeline",
            errors=["无情报微粒数据"],
        )

    try:
        agent = MasterAgent(graph_enabled=False)
        timeline = agent.generate_timeline(
            entity=target_entity,
            particles=particles,
        )

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="timeline",
            data={
                "timeline": timeline,
                "entity": target_entity,
                "event_count": len(timeline.get("events", [])),
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="timeline",
            errors=[f"时间线生成错误: {str(e)}"],
        )


# =============================================================================
# 关系查询节点
# =============================================================================


def relationship_query_node(ctx: PipelineContext) -> StageOutput:
    """关系查询节点

    查询实体间的关系路径。
    需要图谱支持。

    Args:
        ctx: 流流线上下文

    Returns:
        StageOutput: 包含关系路径
    """
    start_time = datetime.now()

    # 检查前置条件
    if not ctx.input or len(ctx.input.entities) < 2:
        return StageOutput.failure(
            stage_name="relationship_query",
            errors=["关系查询需要至少两个实体"],
        )

    if not ctx.graph_enabled:
        return StageOutput.failure(
            stage_name="relationship_query",
            errors=["关系查询需要图谱支持，请启用 graph_enabled"],
        )

    try:
        entities = ctx.input.entities
        particles = ctx.get_particles()

        agent = MasterAgent(graph_enabled=True)

        # 查询两个实体间的关系路径
        report = agent.analyze(
            target_entity=entities[0],
            particles=particles,
        )

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="relationship_query",
            data={
                "report": report.to_dict(),
                "entities": entities,
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="relationship_query",
            errors=[f"关系查询错误: {str(e)}"],
        )


# =============================================================================
# Critic Agent 节点
# =============================================================================


def critic_node(ctx: PipelineContext) -> StageOutput:
    """Critic Agent 节点

    执行事实核查。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含核查结果
    """
    start_time = datetime.now()

    # 获取报告（从 master 或 relationship_query）
    report = {}
    if "master" in ctx.stages and ctx.stages["master"].success:
        report = ctx.stages["master"].data.get("report", {})
    elif "relationship_query" in ctx.stages and ctx.stages["relationship_query"].success:
        report = ctx.stages["relationship_query"].data.get("report", {})

    if not report:
        return StageOutput.failure(
            stage_name="critic",
            errors=["无报告数据"],
        )

    particles = ctx.get_particles()

    try:
        agent = CriticAgent()
        result = agent.verify(
            report=report,
            particles=particles,
        )

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="critic",
            data={
                "passed": result.passed,
                "issues": [i.to_dict() for i in result.issues],
                "suggestions": result.suggestions,
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="critic",
            errors=[f"Critic Agent 错误: {str(e)}"],
        )


# =============================================================================
# 对比分析节点
# =============================================================================


def comparative_analysis_node(ctx: PipelineContext) -> StageOutput:
    """多实体对比分析节点

    对多个实体进行独立分析并生成对比报告。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含对比报告
    """
    start_time = datetime.now()

    # 检查前置条件
    if not ctx.input or len(ctx.input.entities) < 2:
        return StageOutput.failure(
            stage_name="comparative_analysis",
            errors=["对比分析需要至少两个实体"],
        )

    entities = ctx.input.entities
    particles = ctx.get_particles()

    if not particles:
        return StageOutput.failure(
            stage_name="comparative_analysis",
            errors=["无情报微粒数据"],
        )

    try:
        # 为每个实体生成独立的分析
        entity_reports = {}

        for entity in entities:
            # 筛选该实体相关的微粒
            entity_particles = _filter_particles_by_entity(particles, entity)

            agent = MasterAgent(graph_enabled=False)
            report = agent.analyze(
                target_entity=entity,
                particles=entity_particles,
            )
            entity_reports[entity] = report

        # 生成对比报告
        comparison = _generate_comparison_report(entity_reports)

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="comparative_analysis",
            data={
                "comparison_report": comparison,
                "entity_reports": {k: v.to_dict() for k, v in entity_reports.items()},
                "entities": entities,
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="comparative_analysis",
            errors=[f"对比分析错误: {str(e)}"],
        )


def _filter_particles_by_entity(
    particles: list[IntelligenceParticle],
    entity: str,
) -> list[IntelligenceParticle]:
    """筛选与实体相关的情报微粒

    Args:
        particles: 情报微粒列表
        entity: 实体名称

    Returns:
        筛选后的微粒列表
    """
    entity_lower = entity.lower()
    result = []

    for p in particles:
        # 检查风险信号描述
        description = p.risk_signal.description.lower() if p.risk_signal else ""
        if entity_lower in description:
            result.append(p)
            continue

        # 检查来源文档
        source = p.metadata.source.lower() if p.metadata else ""
        if entity_lower in source:
            result.append(p)
            continue

    return result


def _generate_comparison_report(
    entity_reports: dict[str, Any],
) -> dict[str, Any]:
    """生成对比报告

    Args:
        entity_reports: 各实体的分析报告

    Returns:
        对比报告
    """
    entities = list(entity_reports.keys())

    # 提取关键指标进行对比
    comparison = {
        "entities": entities,
        "risk_levels": {},
        "risk_scores": {},
        "key_risks": {},
        "summary": "",
    }

    for entity, report in entity_reports.items():
        comparison["risk_levels"][entity] = report.risk_level
        comparison["risk_scores"][entity] = report.risk_score
        comparison["key_risks"][entity] = report.key_risks[:3] if hasattr(report, "key_risks") else []

    # 生成对比摘要
    if len(entities) >= 2:
        score_a = comparison["risk_scores"].get(entities[0], 0)
        score_b = comparison["risk_scores"].get(entities[1], 0)

        if score_a > score_b:
            comparison["summary"] = f"{entities[0]} 的风险暴露 ({score_a:.2f}) 高于 {entities[1]} ({score_b:.2f})"
        elif score_b > score_a:
            comparison["summary"] = f"{entities[1]} 的风险暴露 ({score_b:.2f}) 高于 {entities[0]} ({score_a:.2f})"
        else:
            comparison["summary"] = f"{entities[0]} 和 {entities[1]} 的风险暴露相当"

    return comparison


# =============================================================================
# 事件影响分析节点
# =============================================================================


def event_impact_node(ctx: PipelineContext) -> StageOutput:
    """事件影响分析节点

    分析特定事件对相关实体的影响范围。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 包含影响分析报告
    """
    start_time = datetime.now()

    particles = ctx.get_particles()

    if not particles:
        return StageOutput.failure(
            stage_name="event_impact",
            errors=["无情报微粒数据"],
        )

    try:
        # 识别关键风险事件
        key_events = _identify_key_events(particles)

        # 分析影响范围
        if ctx.graph_enabled:
            impact_scope = _query_impact_scope_from_graph(key_events, ctx)
        else:
            impact_scope = _estimate_impact_from_particles(particles)

        duration = (datetime.now() - start_time).microseconds // 1000

        return StageOutput.ok(
            stage_name="event_impact",
            data={
                "key_events": key_events,
                "impact_scope": impact_scope,
                "affected_entities": impact_scope.get("entities", []),
            },
            duration_ms=duration,
        )

    except Exception as e:
        return StageOutput.failure(
            stage_name="event_impact",
            errors=[f"事件影响分析错误: {str(e)}"],
        )


def _identify_key_events(
    particles: list[IntelligenceParticle],
) -> list[dict[str, Any]]:
    """识别关键风险事件

    Args:
        particles: 情报微粒列表

    Returns:
        关键事件列表
    """
    from src.schemas.enums import RiskLevel

    key_events = []

    for p in particles:
        if p.risk_signal and p.risk_signal.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            key_events.append({
                "id": p.id,
                "type": p.risk_signal.type.value if p.risk_signal.type else "UNKNOWN",
                "level": p.risk_signal.level.value if hasattr(p.risk_signal.level, "value") else str(p.risk_signal.level),
                "description": p.risk_signal.description,
                "event_time": p.metadata.event_time.isoformat() if p.metadata and p.metadata.event_time else None,
            })

    # 按风险等级排序（CRITICAL 优先）
    key_events.sort(
        key=lambda x: 0 if x["level"] == "CRITICAL" else 1,
    )

    return key_events[:10]  # 返回前 10 个关键事件


def _query_impact_scope_from_graph(
    key_events: list[dict[str, Any]],
    ctx: PipelineContext,
) -> dict[str, Any]:
    """从图谱查询影响范围

    Args:
        key_events: 关键事件列表
        ctx: 流水线上下文

    Returns:
        影响范围
    """
    # TODO: 实现图谱查询
    # 当前返回简化结果
    return {
        "entities": [],
        "paths": [],
        "note": "图谱查询待实现",
    }


def _estimate_impact_from_particles(
    particles: list[IntelligenceParticle],
) -> dict[str, Any]:
    """从情报微粒估算影响范围

    Args:
        particles: 情报微粒列表

    Returns:
        影响范围估算
    """
    entities = set()
    risk_distribution = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for p in particles:
        if p.risk_signal:
            level = p.risk_signal.level
            # 将 RiskLevel 枚举转换为字符串
            level_str = level.value if hasattr(level, "value") else str(level)
            if level_str in risk_distribution:
                risk_distribution[level_str] += 1

            # 从描述中提取实体（简化实现）
            description = p.risk_signal.description
            # TODO: 使用 NER 提取实体

    return {
        "entities": list(entities),
        "risk_distribution": risk_distribution,
        "total_particles": len(particles),
        "note": "基于情报微粒的简化估算",
    }


# =============================================================================
# 最终节点
# =============================================================================


def final_node(ctx: PipelineContext) -> StageOutput:
    """最终节点

    汇总各阶段输出，生成最终结果。

    Args:
        ctx: 流水线上下文

    Returns:
        StageOutput: 最终输出
    """
    start_time = datetime.now()

    # 收集各阶段数据
    final_output: dict[str, Any] = {
        "request_id": ctx.request_id,
        "report": {},
        "risk_assessment": {},
        "timeline_data": {},
        "comparison_report": {},
        "event_impact": {},
        "verification": {
            "passed": ctx.is_verification_passed(),
            "retry_count": ctx.retry_count,
            "issues": [],
        },
        "particles_count": len(ctx.get_particles()),
        "errors": [],
        "stage_durations": {},
    }

    # 收集报告数据
    if "master" in ctx.stages and ctx.stages["master"].success:
        final_output["report"] = ctx.stages["master"].data.get("report", {})
        final_output["risk_assessment"] = {
            "risk_level": ctx.stages["master"].data.get("risk_level"),
            "risk_score": ctx.stages["master"].data.get("risk_score"),
            "target_entity": ctx.stages["master"].data.get("target_entity"),
        }

    # 收集时间线数据
    if "timeline" in ctx.stages and ctx.stages["timeline"].success:
        final_output["timeline_data"] = ctx.stages["timeline"].data

    # 收集对比报告
    if "comparative_analysis" in ctx.stages and ctx.stages["comparative_analysis"].success:
        final_output["comparison_report"] = ctx.stages["comparative_analysis"].data

    # 收集事件影响分析
    if "event_impact" in ctx.stages and ctx.stages["event_impact"].success:
        final_output["event_impact"] = ctx.stages["event_impact"].data

    # 收集核查结果
    if "critic" in ctx.stages:
        critic_data = ctx.stages["critic"].data
        final_output["verification"]["issues"] = critic_data.get("issues", [])

    # 收集错误
    for stage_name, stage in ctx.stages.items():
        if stage.errors:
            final_output["errors"].extend(stage.errors)
        final_output["stage_durations"][stage_name] = stage.duration_ms

    duration = (datetime.now() - start_time).microseconds // 1000

    return StageOutput.ok(
        stage_name="final",
        data=final_output,
        duration_ms=duration,
    )
