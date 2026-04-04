"""
Pipeline 模块

提供两种运行模式的入口：
- continuous: 离线知识化建库（新闻 -> KnowledgeUnit -> Entity/EventCluster -> 图谱）
- task_driven: 知识检索消费（查询 -> KnowledgeUnit/Entity/EventCluster 检索）
"""

from src.pipeline.continuous import ContinuousPipeline, ContinuousRunResult, run_continuous

__all__ = [
    "ContinuousPipeline",
    "ContinuousRunResult",
    "run_continuous",
]
