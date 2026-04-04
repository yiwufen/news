"""
Pipeline 模块

提供两种运行模式的入口：
- continuous: 持续运行模式（新闻 → 情报微粒 → 图谱）
- task_driven: 任务驱动模式（查询 → 检索 → 分析）
"""

from src.pipeline.continuous import ContinuousPipeline, ContinuousRunResult, run_continuous

__all__ = [
    "ContinuousPipeline",
    "ContinuousRunResult",
    "run_continuous",
]
