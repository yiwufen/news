"""
LangGraph 状态图构建

构建多 Agent 编排的状态机图。
"""

from typing import Literal

from langgraph.graph import END, StateGraph

from src.orchestration.nodes import (
    critic_node,
    final_node,
    integrator_node,
    master_node,
    worker_node,
)
from src.orchestration.state import GraphState


def should_retry(state: GraphState) -> Literal["retry", "final"]:
    """判断是否需要重试

    按 CLAUDE.md 规定，max_retries = 2。
    """
    MAX_RETRIES = 2

    # 核查通过，直接结束
    if state.verification_passed:
        return "final"

    # 超过最大重试次数，降级输出
    if state.retry_count >= MAX_RETRIES:
        return "final"

    # 未通过且未超过重试次数，打回重做
    return "retry"


def build_graph() -> StateGraph:
    """构建状态图

    流程：
    Start → Worker → Integrator → Master → Critic
                                        ↓
                              retries < 2? → 打回重做
                              retries >= 2 → 降级输出
                                        ↓
                                     End
    """
    # 创建状态图
    graph = StateGraph(GraphState)

    # 添加节点
    graph.add_node("worker", worker_node)
    graph.add_node("integrator", integrator_node)
    graph.add_node("master", master_node)
    graph.add_node("critic", critic_node)
    graph.add_node("final", final_node)

    # 设置入口
    graph.set_entry_point("worker")

    # 添加边
    graph.add_edge("worker", "integrator")
    graph.add_edge("integrator", "master")
    graph.add_edge("master", "critic")

    # 添加条件边（Critic → Master 或 Final）
    graph.add_conditional_edges(
        "critic",
        should_retry,
        {
            "retry": "master",  # 打回 Master 重做
            "final": "final",   # 结束流程
        },
    )

    # 结束
    graph.add_edge("final", END)

    return graph


# 预编译的图
COMPILED_GRAPH = build_graph().compile()


def run_pipeline(
    articles: list[dict] | None = None,
    query: str = "",
) -> dict:
    """运行完整流水线

    Args:
        articles: 新闻文章列表
        query: 分析查询

    Returns:
        最终输出
    """
    # 初始化状态
    initial_state = GraphState(
        articles=articles or [],
        query=query,
    )

    # 运行图
    result = COMPILED_GRAPH.invoke(initial_state)

    return result
