"""
任务路由器

根据意图类型决定执行路径。
"""

from typing import Literal

from src.intent.models import IntentType


class TaskRouter:
    """任务路由器

    根据意图类型选择执行路径。
    """

    @staticmethod
    def route_by_intent(intent: IntentType | None) -> Literal[
        "entity_timeline_path",
        "risk_assessment_path",
        "relationship_query_path",
        "comparative_analysis_path",
        "event_impact_path",
        "error_path",
    ]:
        """根据意图类型路由

        Args:
            intent: 意图类型

        Returns:
            执行路径名称
        """
        if intent is None:
            return "error_path"

        match intent:
            case IntentType.ENTITY_TIMELINE:
                return "entity_timeline_path"
            case IntentType.RISK_ASSESSMENT:
                return "risk_assessment_path"
            case IntentType.RELATIONSHIP_QUERY:
                return "relationship_query_path"
            case IntentType.COMPARATIVE_ANALYSIS:
                return "comparative_analysis_path"
            case IntentType.EVENT_IMPACT:
                return "event_impact_path"
            case _:
                return "error_path"

    @staticmethod
    def needs_graph_sync(intent: IntentType | None, graph_enabled: bool) -> bool:
        """判断是否需要图谱同步

        Args:
            intent: 意图类型
            graph_enabled: 是否启用图谱

        Returns:
            是否需要图谱同步
        """
        if intent is None:
            return False

        # 关系查询必须依赖图谱
        if intent == IntentType.RELATIONSHIP_QUERY:
            return True

        # 事件影响分析需要图谱（风险传导）
        if intent == IntentType.EVENT_IMPACT:
            return graph_enabled

        # 时间线查询不需要图谱
        if intent == IntentType.ENTITY_TIMELINE:
            return False

        # 对比分析不需要图谱
        if intent == IntentType.COMPARATIVE_ANALYSIS:
            return False

        # 其他意图根据配置决定
        return graph_enabled

    @staticmethod
    def needs_critic(intent: IntentType | None) -> bool:
        """判断是否需要 Critic 核查

        Args:
            intent: 意图类型

        Returns:
            是否需要核查
        """
        if intent is None:
            return False

        # 时间线和对比分析是事实罗列，不需要核查
        if intent in (IntentType.ENTITY_TIMELINE, IntentType.COMPARATIVE_ANALYSIS):
            return False

        # 其他意图需要核查（可能产生幻觉）
        return True
