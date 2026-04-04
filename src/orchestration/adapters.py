"""
节点适配器

将 StageOutput 节点函数适配为 LangGraph 需要的格式。
"""

from __future__ import annotations

from typing import Callable

from src.orchestration.state import PipelineContext, StageOutput


def wrap_node(
    func: Callable[[PipelineContext], StageOutput],
) -> Callable[[PipelineContext], dict]:
    """将 StageOutput 节点函数适配为 LangGraph 需要的格式

    LangGraph 的节点函数需要返回 dict 来更新状态。
    此适配器：
    1. 调用原始节点函数获取 StageOutput
    2. 将 StageOutput 写入 PipelineContext.stages
    3. 更新 current_stage
    4. 返回 LangGraph 需要的 dict

    Args:
        func: 返回 StageOutput 的节点函数

    Returns:
        适配后的节点函数，返回 dict

    Example:
        >>> def retrieval_node(ctx: PipelineContext) -> StageOutput:
        ...     return StageOutput.ok("retrieval", {"count": 10})
        >>>
        >>> graph.add_node("retrieval", wrap_node(retrieval_node))
    """

    def wrapper(state: PipelineContext) -> dict:
        # 执行节点函数
        output = func(state)

        # 更新上下文
        state.stages[output.stage_name] = output
        state.current_stage = output.stage_name

        # 返回 LangGraph 需要的状态更新
        return {
            "stages": state.stages,
            "current_stage": output.stage_name,
        }

    return wrapper


def wrap_node_with_retry_increment(
    func: Callable[[PipelineContext], StageOutput],
) -> Callable[[PipelineContext], dict]:
    """带重试计数递增的节点适配器

    用于 Critic 节点，在每次执行后递增 retry_count。

    Args:
        func: 返回 StageOutput 的节点函数

    Returns:
        适配后的节点函数
    """

    def wrapper(state: PipelineContext) -> dict:
        output = func(state)

        state.stages[output.stage_name] = output
        state.current_stage = output.stage_name

        # 如果核查未通过，递增重试计数
        if not output.data.get("passed", False):
            state.retry_count += 1

        return {
            "stages": state.stages,
            "current_stage": output.stage_name,
            "retry_count": state.retry_count,
        }

    return wrapper
