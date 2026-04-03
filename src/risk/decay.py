"""
时间衰减计算

按 .claude/rules/03-risk-logic.md 定义的时间衰减规则。
"""

from datetime import date, timedelta
from typing import Callable


def calculate_time_decay(
    event_date: date,
    reference_date: date | None = None,
) -> float:
    """计算时间衰减系数

    时间衰减规则：
    - 3 个月内: 1.0 (全权重，当前风险)
    - 3-6 个月: 0.7 (高相关性，近期风险)
    - 6-12 个月: 0.4 (中等相关，趋势风险)
    - 1 年以上: 0.1 (低相关，历史背景)

    Args:
        event_date: 事件发生日期
        reference_date: 参考日期（默认为今天）

    Returns:
        时间衰减系数 (0-1)
    """
    if reference_date is None:
        reference_date = date.today()

    days_diff = (reference_date - event_date).days

    if days_diff <= 90:
        return 1.0
    elif days_diff <= 180:
        return 0.7
    elif days_diff <= 365:
        return 0.4
    else:
        return 0.1


def get_decay_bucket(days: int) -> tuple[str, float]:
    """获取天数对应的衰减区间和系数

    Args:
        days: 天数差

    Returns:
        (区间名称, 衰减系数)
    """
    if days <= 90:
        return ("3个月内", 1.0)
    elif days <= 180:
        return ("3-6个月", 0.7)
    elif days <= 365:
        return ("6-12个月", 0.4)
    else:
        return ("1年以上", 0.1)


# === 可自定义的衰减函数 ===


def linear_decay(
    event_date: date,
    reference_date: date | None = None,
    half_life_days: int = 180,
) -> float:
    """线性衰减函数

    Args:
        event_date: 事件发生日期
        reference_date: 参考日期
        half_life_days: 半衰期（衰减到 0.5 的天数）

    Returns:
        衰减系数
    """
    if reference_date is None:
        reference_date = date.today()

    days_diff = (reference_date - event_date).days
    if days_diff <= 0:
        return 1.0

    decay = 1.0 - (days_diff / (half_life_days * 2))
    return max(0.1, min(1.0, decay))


def exponential_decay(
    event_date: date,
    reference_date: date | None = None,
    half_life_days: int = 180,
) -> float:
    """指数衰减函数

    Args:
        event_date: 事件发生日期
        reference_date: 参考日期
        half_life_days: 半衰期

    Returns:
        衰减系数
    """
    import math

    if reference_date is None:
        reference_date = date.today()

    days_diff = (reference_date - event_date).days
    if days_diff <= 0:
        return 1.0

    # 指数衰减: decay = 2^(-days/half_life)
    decay = math.exp(-days_diff * math.log(2) / half_life_days)
    return max(0.1, min(1.0, decay))
