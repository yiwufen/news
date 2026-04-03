"""
风险模型定义

风险路径、风险因子等数据结构。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class RiskPath:
    """风险传导路径

    表示从源头风险到目标实体的传导路径。
    """

    source_id: str  # 源节点 ID
    source_risk: float  # 源头风险分值 (0-1)
    path_weight: float  # 路径传导系数 (0-1)
    time_decay: float  # 时间衰减系数 (0-1)
    relation_chain: list[str] = field(default_factory=list)  # 关系链路
    event_date: date | None = None  # 事件发生日期
    properties: dict[str, Any] = field(default_factory=dict)  # 扩展属性

    @property
    def weighted_risk(self) -> float:
        """计算加权风险分值"""
        return self.source_risk * self.path_weight * self.time_decay


@dataclass
class RiskFactor:
    """风险因子

    单个风险因子的描述。
    """

    factor_id: str
    factor_type: str  # DEBT_DEFAULT, EQUITY_PLEDGE 等
    factor_score: float  # 因子分值 (0-1)
    description: str
    source_doc_ids: list[str] = field(default_factory=list)


@dataclass
class RiskAssessment:
    """风险评估结果

    对目标实体的综合风险评估。
    """

    target_id: str
    target_name: str
    total_risk_score: float
    risk_level: str  # CRITICAL, HIGH, MEDIUM, LOW
    risk_factors: list[RiskFactor] = field(default_factory=list)
    risk_paths: list[RiskPath] = field(default_factory=list)
    source_doc_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "target_id": self.target_id,
            "target_name": self.target_name,
            "total_risk_score": self.total_risk_score,
            "risk_level": self.risk_level,
            "risk_factors": [
                {
                    "factor_id": f.factor_id,
                    "factor_type": f.factor_type,
                    "factor_score": f.factor_score,
                    "description": f.description,
                }
                for f in self.risk_factors
            ],
            "risk_paths": [
                {
                    "source_id": p.source_id,
                    "source_risk": p.source_risk,
                    "path_weight": p.path_weight,
                    "time_decay": p.time_decay,
                    "relation_chain": p.relation_chain,
                }
                for p in self.risk_paths
            ],
        }
