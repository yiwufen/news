"""
LangGraph 状态图构建

使用 PipelineContext 和 StageOutput 的状态机。
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from src.orchestration.adapters import wrap_node, wrap_node_with_retry_increment
from src.orchestration.nodes import (
    comparative_analysis_node,
    critic_node,
    event_impact_node,
    final_node,
    intent_parse_node,
    integrator_node,
    master_node,
    relationship_query_node,
    retrieval_node,
    timeline_node,
    worker_node,
)
from src.orchestration.state import PipelineContext
from src.routing.router import TaskRouter


# =============================================================================
# 条件判断函数
# =============================================================================


def route_by_intent(state: PipelineContext) -> Literal[
    "entity_timeline_path",
    "risk_assessment_path",
    "relationship_query_path",
    "comparative_analysis_path",
    "event_impact_path",
    "error_path",
]:
    """根据意图类型路由到不同的执行路径

    Args:
        state: 流水线上下文

    Returns:
        下一个节点名称
    """
    intent = state.input.intent if state.input else None
    return TaskRouter.route_by_intent(intent)


def should_retry(state: PipelineContext) -> Literal["retry", "final"]:
    """判断是否需要重试

    按 CLAUDE.md 规定，max_retries = 2。

    Args:
        state: 流水线上下文

    Returns:
        路由结果
    """
    MAX_RETRIES = 2

    # 核查通过，直接结束
    if state.is_verification_passed():
        return "final"

    # 超过最大重试次数，降级输出
    if state.retry_count >= MAX_RETRIES:
        return "final"

    return "retry"


# =============================================================================
# 状态图构建
# =============================================================================


def build_graph() -> StateGraph:
    """构建任务驱动状态图

    流程：
    Start → IntentParse → Retrieval → [路由判断]
                                         │
        ┌────────────────────────────────┼────────────────────────────────────┐
        │                                │                                    │
        ▼                                ▼                                    ▼
    ENTITY_TIMELINE               RISK_ASSESSMENT                    COMPARATIVE_ANALYSIS
        │                                │                                    │
        ▼                                ▼                                    │
    TimelineNode                  Worker → Integrator                       │
        │                                │                                    │
        │                                ▼                                    │
        │                             Master                                  │
        │                                │                                    │
        │                                ▼                                    │
        │                             Critic                                  │
        │                                │                                    │
        │                    ┌───────────┴───────────┐                        │
        │                 retry                    pass                       │
        │                    │                       │                        │
        │                    ▼                       ▼                        │
        │                 Master                   Final  ←───────────────────┘
        │                    │
        └────────────────────┴──────────────────────────────→ End

    同时支持：
    - RELATIONSHIP_QUERY → relationship_query → critic → final
    - EVENT_IMPACT → event_impact → critic → final
    """
    graph = StateGraph(PipelineContext)

    # === 注册节点 ===
    # Note: Pyright 对 LangGraph 节点函数的类型推断有限制，使用 type: ignore 绕过
    graph.add_node("intent_parse", wrap_node(intent_parse_node))  # type: ignore[arg-type]
    graph.add_node("retrieval", wrap_node(retrieval_node))  # type: ignore[arg-type]
    graph.add_node("timeline", wrap_node(timeline_node))  # type: ignore[arg-type]
    graph.add_node("worker", wrap_node(worker_node))  # type: ignore[arg-type]
    graph.add_node("integrator", wrap_node(integrator_node))  # type: ignore[arg-type]
    graph.add_node("master", wrap_node(master_node))  # type: ignore[arg-type]
    graph.add_node("critic", wrap_node_with_retry_increment(critic_node))  # type: ignore[arg-type]
    graph.add_node("relationship_query", wrap_node(relationship_query_node))  # type: ignore[arg-type]
    graph.add_node("comparative_analysis", wrap_node(comparative_analysis_node))  # type: ignore[arg-type]
    graph.add_node("event_impact", wrap_node(event_impact_node))  # type: ignore[arg-type]
    graph.add_node("final", wrap_node(final_node))  # type: ignore[arg-type]

    # === 设置入口 ===
    graph.set_entry_point("intent_parse")

    # === 定义边 ===

    # intent_parse → retrieval
    graph.add_edge("intent_parse", "retrieval")

    # retrieval → 按意图路由
    graph.add_conditional_edges(
        "retrieval",
        route_by_intent,
        {
            "entity_timeline_path": "timeline",
            "risk_assessment_path": "worker",
            "relationship_query_path": "relationship_query",
            "comparative_analysis_path": "comparative_analysis",
            "event_impact_path": "event_impact",
            "error_path": "final",
        },
    )

    # ENTITY_TIMELINE 路径：timeline → final
    graph.add_edge("timeline", "final")

    # RISK_ASSESSMENT 路径：worker → integrator → master → critic
    graph.add_edge("worker", "integrator")
    graph.add_edge("integrator", "master")
    graph.add_edge("master", "critic")

    # RELATIONSHIP_QUERY 路径：relationship_query → critic
    graph.add_edge("relationship_query", "critic")

    # COMPARATIVE_ANALYSIS 路径：comparative_analysis → final（无需 Critic）
    graph.add_edge("comparative_analysis", "final")

    # EVENT_IMPACT 路径：event_impact → critic
    graph.add_edge("event_impact", "critic")

    # Critic 重试逻辑
    graph.add_conditional_edges(
        "critic",
        should_retry,
        {
            "retry": "master",
            "final": "final",
        },
    )

    # final → END
    graph.add_edge("final", END)

    return graph


# 预编译图
COMPILED_GRAPH = build_graph().compile()


# =============================================================================
# 入口函数
# =============================================================================


def run_pipeline(
    raw_query: str = "",
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
) -> dict:
    """运行任务驱动流水线

    Args:
        raw_query: 用户自然语言查询
        articles: 直接传入的文章列表（可选）
        graph_enabled: 是否启用图谱同步

    Returns:
        最终输出
    """
    from src.orchestration.state import QueryInput, StageOutput

    # 构建上下文
    ctx = PipelineContext(
        input=QueryInput(raw_query=raw_query),
        graph_enabled=graph_enabled,
    )

    # 如果直接传入文章，注入到上下文
    if articles:
        ctx.stages["input"] = StageOutput.ok(
            stage_name="input",
            data={"articles": articles},
        )

    # 运行图
    result = COMPILED_GRAPH.invoke(ctx)

    # result 可能是 PipelineContext 或 dict
    if isinstance(result, PipelineContext):
        stages = result.stages
    else:
        stages = result.get("stages", {})

    # 返回最终输出
    final_stage = stages.get("final")
    if final_stage and final_stage.success:
        return final_stage.data

    # 如果没有 final 阶段，返回错误
    return {
        "error": "流水线执行失败",
        "stages": {k: v.to_dict() if hasattr(v, "to_dict") else v for k, v in stages.items()},
    }
