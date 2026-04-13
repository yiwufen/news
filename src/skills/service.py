"""
Skill-facing retrieval adapter over the raw retrieval pipeline.
"""

from __future__ import annotations

from typing import Any

from src.intent.models import IntentType, StructuredQuery
from src.orchestration.graph import run_pipeline
from src.orchestration.result import PipelineResult
from src.skills.models import (
    SkillCapabilities,
    SkillContract,
    SkillSource,
    SkillSummary,
    SkillType,
)
from src.skills.payloads import (
    build_payload,
    normalize_supporting_evidence,
    sort_clusters_desc,
    target_entity as get_target_entity,
)

SUPPORTED_INTENTS: dict[str, SkillType] = {
    IntentType.ENTITY_OVERVIEW.value: "entity_overview",
    IntentType.ENTITY_TIMELINE.value: "entity_timeline",
    IntentType.EVENT_ANALYSIS.value: "event_analysis",
    IntentType.RELATIONSHIP_QUERY.value: "relationship_query",
    IntentType.RISK_ASSESSMENT.value: "risk_assessment",
    IntentType.GUARANTEE_ANALYSIS.value: "guarantee_analysis",
    IntentType.TOPIC_RESEARCH.value: "topic_research",
    IntentType.EVENT_IMPACT_ANALYSIS.value: "event_impact_analysis",
}
SKILL_TYPE_TO_INTENT: dict[SkillType, str] = {
    skill_type: intent for intent, skill_type in SUPPORTED_INTENTS.items()
}


def _build_summary(result: PipelineResult) -> SkillSummary:
    return SkillSummary(
        knowledge_unit_count=len(result.knowledge_units),
        entity_count=len(result.entities),
        event_cluster_count=len(result.event_clusters),
        total_count=result.total_count,
    )


def _is_non_blocking_skill_error(error: Any) -> bool:
    return isinstance(error, str) and error.startswith("[graph] ")


def _contract_ok(result: PipelineResult) -> bool:
    if result.query.intent == IntentType.RELATIONSHIP_QUERY and result.source != "knowledge_base":
        return False
    return all(_is_non_blocking_skill_error(error) for error in result.errors)


def _build_capabilities(result: PipelineResult, *, skill_type: SkillType | None) -> SkillCapabilities:
    graph_supported = result.source == "knowledge_base"
    graph_used = result.graph.graph_used if graph_supported else False
    return SkillCapabilities(
        graph_supported=graph_supported,
        graph_used=graph_used,
        timeline_supported=skill_type == "entity_timeline",
    )


def _error_contract(errors: list[str], result: PipelineResult | None = None) -> SkillContract:
    source_value: SkillSource | None = result.source if result else None
    return SkillContract(
        ok=False,
        skill_type=None,
        source=source_value,
        query=result.query.to_dict() if result else {},
        summary=_build_summary(result) if result else SkillSummary(),
        capabilities=_build_capabilities(result, skill_type=None) if result else SkillCapabilities(
            graph_supported=False,
            graph_used=False,
            timeline_supported=False,
        ),
        payload=None,
        verification={},
        errors=errors,
    )


def run_skill_query(
    raw_query: str = "",
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
    skill_type_override: SkillType | None = None,
    structured_query: StructuredQuery | None = None,
) -> dict[str, Any]:
    """Run the stable skill-facing retrieval contract over the knowledge foundation.

    ``articles`` is an ad-hoc/debug path inherited from ``run_pipeline`` and is
    not the formal knowledge-base ingestion route. ``graph_enabled=False`` is
    reserved for tests, debugging, and local triage.
    """
    pipeline_result = run_pipeline(
        raw_query=raw_query,
        articles=articles,
        graph_enabled=graph_enabled,
        structured_query=structured_query,
    )

    intent = pipeline_result.query.intent.value
    skill_type = skill_type_override or SUPPORTED_INTENTS.get(intent)
    if skill_type is None:
        return _error_contract([f"unsupported_intent:{intent}"], pipeline_result).model_dump(mode="json")

    query_payload = pipeline_result.query.to_dict()
    if skill_type_override is not None:
        query_payload["intent"] = SKILL_TYPE_TO_INTENT[skill_type_override]

    knowledge_units = pipeline_result.knowledge_units
    event_clusters = pipeline_result.event_clusters
    entities = pipeline_result.entities
    target_entity = get_target_entity(pipeline_result)
    sorted_clusters = sort_clusters_desc(event_clusters)
    supporting_evidence = normalize_supporting_evidence(knowledge_units)

    payload = build_payload(
        pipeline_result,
        skill_type,
        knowledge_units=knowledge_units,
        event_clusters=event_clusters,
        entities=entities,
        target_entity=target_entity,
        sorted_clusters=sorted_clusters,
        supporting_evidence=supporting_evidence,
    )

    source_value: SkillSource | None = pipeline_result.source

    contract_ok = _contract_ok(pipeline_result)
    contract = SkillContract(
        ok=contract_ok,
        skill_type=skill_type,
        source=source_value,
        query=query_payload,
        summary=_build_summary(pipeline_result),
        capabilities=_build_capabilities(pipeline_result, skill_type=skill_type),
        payload=payload,
        verification={"passed": contract_ok, "retry_count": 0, "issues": []},
        errors=list(pipeline_result.errors),
    )
    return contract.model_dump(mode="json")
