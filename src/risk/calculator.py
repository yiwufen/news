"""
风险计算器

核心风险传导计算逻辑。
按 .claude/rules/03-risk-logic.md 定义。
"""

from datetime import date

from src.risk.decay import calculate_time_decay
from src.risk.models import RiskAssessment, RiskFactor, RiskPath
from src.risk.weights import calculate_path_weight, get_relation_weight, get_risk_level
from src.schemas.enums import RelationType


class RiskCalculator:
    """风险计算器

    实现风险传导公式：
    Target_Risk = Σ(Source_Risk × Path_Weight × Time_Decay)
    """

    # 配置参数
    MAX_RISK_SCORE = 1.0  # 最大风险分值
    MIN_RISK_THRESHOLD = 0.3  # 最小风险阈值（低于此值不纳入报告）

    @classmethod
    def calculate_target_risk(
        cls,
        paths: list[RiskPath],
    ) -> float:
        """计算目标实体的综合风险分值

        核心公式：Target_Risk = Σ(Source_Risk × Path_Weight × Time_Decay)

        Args:
            paths: 风险传导路径列表

        Returns:
            综合风险分值 (0-1)
        """
        if not paths:
            return 0.0

        total_risk = sum(p.weighted_risk for p in paths)
        return min(total_risk, cls.MAX_RISK_SCORE)

    @classmethod
    def calculate_single_path(
        cls,
        source_risk: float,
        relations: list[RelationType],
        event_date: date,
        reference_date: date | None = None,
    ) -> float:
        """计算单条路径的风险传导

        Args:
            source_risk: 源头风险分值
            relations: 关系链路
            event_date: 事件日期
            reference_date: 参考日期

        Returns:
            传导后的风险分值
        """
        path_weight = calculate_path_weight(relations)
        time_decay = calculate_time_decay(event_date, reference_date)

        return source_risk * path_weight * time_decay

    @classmethod
    def assess_entity(
        cls,
        target_id: str,
        target_name: str,
        risk_paths: list[RiskPath],
        risk_factors: list[RiskFactor] | None = None,
    ) -> RiskAssessment:
        """对目标实体进行风险评估

        Args:
            target_id: 目标实体 ID
            target_name: 目标实体名称
            risk_paths: 风险传导路径
            risk_factors: 风险因子

        Returns:
            风险评估结果
        """
        # 计算综合风险分值
        total_score = cls.calculate_target_risk(risk_paths)

        # 判定风险等级
        risk_level = get_risk_level(total_score)

        # 收集来源文档
        source_doc_ids: list[str] = []
        for path in risk_paths:
            if path.properties.get("source_doc_ids"):
                source_doc_ids.extend(path.properties["source_doc_ids"])
        for factor in risk_factors or []:
            source_doc_ids.extend(factor.source_doc_ids)

        return RiskAssessment(
            target_id=target_id,
            target_name=target_name,
            total_risk_score=round(total_score, 3),
            risk_level=risk_level,
            risk_factors=risk_factors or [],
            risk_paths=risk_paths,
            source_doc_ids=list(set(source_doc_ids)),
        )

    @classmethod
    def filter_significant_paths(
        cls,
        paths: list[RiskPath],
        min_threshold: float | None = None,
    ) -> list[RiskPath]:
        """过滤显著的风险路径

        Args:
            paths: 风险路径列表
            min_threshold: 最小阈值（默认使用 MIN_RISK_THRESHOLD）

        Returns:
            过滤后的路径列表
        """
        threshold = min_threshold or cls.MIN_RISK_THRESHOLD
        return [p for p in paths if p.weighted_risk >= threshold]

    @classmethod
    def sort_paths_by_risk(
        cls,
        paths: list[RiskPath],
        descending: bool = True,
    ) -> list[RiskPath]:
        """按风险分值排序路径

        Args:
            paths: 风险路径列表
            descending: 是否降序排列

        Returns:
            排序后的路径列表
        """
        return sorted(paths, key=lambda p: p.weighted_risk, reverse=descending)
