"""
枚举定义模块

按 .claude/rules/01-taxonomy.md 定义所有枚举类型。
"""

from enum import Enum


class EventType(Enum):
    """事件类型枚举 (risk_signal.type)"""

    DEBT_DEFAULT = "债务违约"
    EQUITY_PLEDGE = "股权质押"
    LEGAL_SUIT = "重大诉讼"
    REAL_CONTROL_CHANGE = "实控人变动"
    RESTRUCTURING = "资产重组"
    POLICY_SANCTION = "政策制裁"


class RelationType(Enum):
    """关系类型枚举 (edges.relation)"""

    INVESTS = "股权投资"
    GUARANTEES = "担保"
    DEBTOR_OF = "债权债务"
    ACTUAL_CONTROL = "实际控制"
    OWNS = "资产所有权"
    ISSUES = "发行产品"


class EntityType(Enum):
    """实体类型枚举 (nodes.type)"""

    COMPANY = "公司实体"
    PERSON = "自然人"
    ASSET = "资产"
    FINANCIAL_PRODUCT = "金融产品"


class RiskLevel(Enum):
    """风险等级枚举 (risk_signal.level)"""

    CRITICAL = "立即预警"
    HIGH = "当日处理"
    MEDIUM = "周报汇总"
    LOW = "归档记录"


def classify_risk_score(score: float) -> RiskLevel:
    """根据分值判定风险等级

    Args:
        score: 风险分值 (0-1)

    Returns:
        RiskLevel 枚举值
    """
    if score >= 0.8:
        return RiskLevel.CRITICAL
    elif score >= 0.6:
        return RiskLevel.HIGH
    elif score >= 0.4:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.LOW
