"""
LangGraph 状态定义

定义多 Agent 流水线的全局状态。
"""

from dataclasses import dataclass, field
from typing import Any

from src.schemas import IntelligenceParticle


@dataclass
class GraphState:
    """LangGraph 全局状态

    在各个 Agent 节点之间传递的状态对象。
    """

    # === 输入数据 ===
    # 原始新闻文章
    articles: list[dict[str, Any]] = field(default_factory=list)
    # 分析查询
    query: str = ""

    # === 处理状态 ===
    # 当前处理阶段
    current_stage: str = "init"
    # 错误信息
    errors: list[str] = field(default_factory=list)

    # === Worker Agent 输出 ===
    # 提取的情报微粒
    particles: list[IntelligenceParticle] = field(default_factory=list)

    # === Integrator Agent 输出 ===
    # 实体对齐结果
    alignment_results: list[dict[str, Any]] = field(default_factory=list)
    # 图谱同步结果
    sync_result: dict[str, Any] = field(default_factory=dict)

    # === Master Agent 输出 ===
    # 分析报告
    report: dict[str, Any] = field(default_factory=dict)
    # 风险评估
    risk_assessment: dict[str, Any] = field(default_factory=dict)

    # === Critic Agent 输出 ===
    # 核查结果
    verification_result: dict[str, Any] = field(default_factory=dict)
    # 重试次数
    retry_count: int = 0
    # 是否通过核查
    verification_passed: bool = False

    # === 输出 ===
    # 最终输出
    final_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "articles": self.articles,
            "query": self.query,
            "current_stage": self.current_stage,
            "errors": self.errors,
            "particles": [p.model_dump() for p in self.particles],
            "alignment_results": self.alignment_results,
            "sync_result": self.sync_result,
            "report": self.report,
            "risk_assessment": self.risk_assessment,
            "verification_result": self.verification_result,
            "retry_count": self.retry_count,
            "verification_passed": self.verification_passed,
            "final_output": self.final_output,
        }
