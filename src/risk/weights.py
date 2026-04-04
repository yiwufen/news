"""
传导权重定义

按 .claude/rules/01-taxonomy.md 和 03-risk-logic.md 定义。
"""

from src.schemas.enums import RelationType, RiskLevel


# === 传导权重表 ===
# 按 01-taxonomy.md 定义

RELATION_WEIGHTS: dict[RelationType, float] = {
    RelationType.ACTUAL_CONTROL: 0.9,  # 控股关系，直接联动，风险高度相关
    RelationType.GUARANTEES: 0.8,  # 关联担保，代偿风险，需重点关注
    RelationType.INVESTS: 0.7,  # 股权投资
    RelationType.OWNS: 0.6,  # 资产所有权
    RelationType.DEBTOR_OF: 0.5,  # 债权债务
    RelationType.ISSUES: 0.3,  # 业务依赖，订单风险，影响相对间接
}


def get_relation_weight(relation: RelationType) -> float:
    """获取关系类型的传导权重

    Args:
        relation: 关系类型

    Returns:
        传导权重 (0-1)
    """
    return RELATION_WEIGHTS.get(relation, 0.3)


def calculate_path_weight(
    relations: list[RelationType],
    aggregation: str = "multiply",
) -> float:
    """计算多跳路径的累积权重

    Args:
        relations: 关系类型列表（按路径顺序）
        aggregation: 聚合方式 ("multiply" | "min" | "average")

    Returns:
        累积权重 (0-1)
    """
    if not relations:
        return 0.0

    weights = [get_relation_weight(r) for r in relations]

    if aggregation == "multiply":
        # 连乘：路径越长，权重越低
        result = 1.0
        for w in weights:
            result *= w
        return result
    elif aggregation == "min":
        # 最小值：取路径中最弱的环节
        return min(weights)
    elif aggregation == "average":
        # 平均值
        return sum(weights) / len(weights)
    else:
        return sum(weights) / len(weights)


# === 风险等级阈值 ===

RISK_LEVEL_THRESHOLDS: dict[str, tuple[float, float]] = {
    "CRITICAL": (0.8, 1.0),  # 立即预警，人工介入
    "HIGH": (0.6, 0.8),  # 当日处理，持续监控
    "MEDIUM": (0.4, 0.6),  # 周报汇总，定期复查
    "LOW": (0.0, 0.4),  # 归档记录，作为背景信息
}


def get_risk_level(score: float) -> str:
    """根据分值判定风险等级

    委托给 src.schemas.enums.classify_risk_score 实现，
    保持向后兼容的字符串返回值。

    Args:
        score: 风险分值 (0-1)

    Returns:
        风险等级名称 (CRITICAL/HIGH/MEDIUM/LOW)
    """
    from src.schemas.enums import classify_risk_score

    return classify_risk_score(score).name


def get_risk_threshold(level: str) -> tuple[float, float]:
    """获取风险等级的分值范围

    Args:
        level: 风险等级

    Returns:
        (最小值, 最大值)
    """
    return RISK_LEVEL_THRESHOLDS.get(level, (0.0, 0.4))
