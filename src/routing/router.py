"""Intent-aware routing helpers for the retrieval pipeline."""

from typing import Literal

from src.intent.models import IntentType


class TaskRouter:
    """Choose downstream paths and optional checks from the parsed intent."""

    @staticmethod
    def route_by_intent(intent: IntentType | None) -> Literal[
        "entity_timeline_path",
        "entity_overview_path",
        "relationship_query_path",
        "comparative_analysis_path",
        "event_analysis_path",
        "error_path",
    ]:
        if intent is None:
            return "error_path"

        match intent:
            case IntentType.ENTITY_TIMELINE:
                return "entity_timeline_path"
            case IntentType.ENTITY_OVERVIEW:
                return "entity_overview_path"
            case IntentType.RELATIONSHIP_QUERY:
                return "relationship_query_path"
            case IntentType.COMPARATIVE_ANALYSIS:
                return "comparative_analysis_path"
            case IntentType.EVENT_ANALYSIS:
                return "event_analysis_path"
            case _:
                return "error_path"

    @staticmethod
    def needs_graph_sync(intent: IntentType | None, graph_enabled: bool) -> bool:
        if intent is None:
            return False

        if intent == IntentType.RELATIONSHIP_QUERY:
            return True

        if intent == IntentType.EVENT_ANALYSIS:
            return graph_enabled

        if intent in (IntentType.ENTITY_TIMELINE, IntentType.COMPARATIVE_ANALYSIS):
            return False

        return graph_enabled

    @staticmethod
    def needs_critic(intent: IntentType | None) -> bool:
        if intent is None:
            return False

        if intent in (IntentType.ENTITY_TIMELINE, IntentType.COMPARATIVE_ANALYSIS):
            return False

        return True
