"""
Orchestration 模块

LangGraph 多 Agent 编排。

核心组件：
- PipelineContext: 流水线上下文，职责分离
- QueryInput: 用户输入模型
- StageOutput: 阶段输出模型
- run_pipeline: 任务驱动流水线入口
"""

from src.orchestration.graph import (
    COMPILED_GRAPH,
    build_graph,
    run_pipeline,
)
from src.orchestration.state import PipelineContext, QueryInput, StageOutput

__all__ = [
    # 核心数据结构
    "PipelineContext",
    "QueryInput",
    "StageOutput",
    # 状态机
    "build_graph",
    "COMPILED_GRAPH",
    "run_pipeline",
]
