"""
Skill-facing retrieval adapter over the raw retrieval pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.entities import entity_matches_query_name
from src.intent.models import IntentType
from src.orchestration.graph import run_pipeline
from src.skills.models import (
    EntityOverviewPayload,
    EntityTimelinePayload,
    EventAnalysisPayload,
    RelationshipGraph,
    RelationshipPath,
    RelationshipQueryPayload,
    SkillCapabilities,
    SkillContract,
    SkillType,
    SkillSummary,
    SupportingEvidence,
    TimelineEvent,
)


SUPPORTED_INTENTS: dict[str, SkillType] = {
    IntentType.ENTITY_OVERVIEW.value: "entity_overview",
    IntentType.ENTITY_TIMELINE.value: "entity_timeline",
    IntentType.EVENT_ANALYSIS.value: "event_analysis",
    IntentType.RELATIONSHIP_QUERY.value: "relationship_query",
}


def _normalize_supporting_evidence(units: list[dict[str, Any]]) -> list[SupportingEvidence]:
    return [
        SupportingEvidence(
            ku_id=unit["ku_id"],
            unit_kind=unit["unit_kind"],
            unit_type=unit["unit_type"],
            summary=unit["summary"],
            entities=list(unit.get("entities", [])),
            source=dict(unit.get("source", {})),
            evidence=list(unit.get("evidence", [])),
            confidence=float(unit.get("confidence", 0.0)),
            conflict_status=str(unit.get("conflict_status", "none")),
            cluster_id=unit.get("cluster_id"),
        )
        for unit in units
    ]


def _parse_anchor(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(text), datetime.min.time())
            except ValueError:
                return None
    return None


def _cluster_sort_anchor(cluster: dict[str, Any]) -> datetime:
    time_range = cluster.get("time_range") or {}
    candidates = (
        cluster.get("time_anchor"),
        time_range.get("end"),
        time_range.get("start"),
    )
    for candidate in candidates:
        parsed = _parse_anchor(candidate)
        if parsed is not None:
            return parsed
    return datetime.min


def _build_summary(raw_result: dict[str, Any]) -> SkillSummary:
    return SkillSummary(
        knowledge_unit_count=len(raw_result.get("knowledge_units", [])),
        entity_count=len(raw_result.get("entities", [])),
        event_cluster_count=len(raw_result.get("event_clusters", [])),
        total_count=int(raw_result.get("total_count", 0)),
    )


def _is_non_blocking_skill_error(error: Any) -> bool:
    return isinstance(error, str) and error.startswith("[graph] ")


def _verification_passed(verification: Any) -> bool:
    """Check if verification passed. Returns True if passed or not explicitly failed."""
    if not isinstance(verification, dict):
        return True
    return verification.get("passed") is not False


def _contract_ok(raw_result: dict[str, Any]) -> bool:
    if not _verification_passed(raw_result.get("verification")):
        return False

    errors = raw_result.get("errors", [])
    if not isinstance(errors, list):
        return False
    return all(_is_non_blocking_skill_error(error) for error in errors)


def _build_capabilities(raw_result: dict[str, Any], *, skill_type: SkillType | None) -> SkillCapabilities:
    source = raw_result.get("source")
    graph_supported = source == "knowledge_base"
    graph_used = bool(raw_result.get("retrieval", {}).get("graph_used")) if graph_supported else False
    return SkillCapabilities(
        graph_supported=graph_supported,
        graph_used=graph_used,
        timeline_supported=skill_type == "entity_timeline",
    )


def _target_entity(raw_result: dict[str, Any]) -> str | None:
    entities = raw_result.get("query", {}).get("entities", [])
    if isinstance(entities, list) and entities:
        first = entities[0]
        if isinstance(first, str):
            return first
    return None


def _is_target_entity(entity: dict[str, Any], target_entity: str | None) -> bool:
    if not target_entity:
        return False
    names = [entity.get("canonical_name", ""), *entity.get("aliases", [])]
    return entity_matches_query_name(names, target_entity)


def _sort_clusters_desc(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        clusters,
        key=lambda cluster: (_cluster_sort_anchor(cluster), cluster.get("cluster_id", "")),
        reverse=True,
    )


def _build_entity_overview_payload(
    entities: list[dict[str, Any]],
    target_entity: str | None,
    sorted_clusters: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> EntityOverviewPayload:
    related_entities = _filter_related_entities(entities, target_entity=target_entity)
    return EntityOverviewPayload(
        target_entity=target_entity,
        recent_event_clusters=sorted_clusters,
        related_entities=related_entities,
        supporting_evidence=supporting_evidence,
    )


def _timeline_event_from_cluster(cluster: dict[str, Any]) -> TimelineEvent:
    time_range = cluster.get("time_range")
    date_value = cluster.get("time_anchor")
    if date_value is None and isinstance(time_range, dict):
        date_value = time_range.get("start") or time_range.get("end")
    return TimelineEvent(
        event_id=cluster["cluster_id"],
        event_source="event_cluster",
        event_type=cluster["cluster_type"],
        title=cluster.get("title") or cluster.get("summary") or cluster["cluster_id"],
        summary=cluster.get("summary") or cluster.get("title") or cluster["cluster_id"],
        date=date_value,
        time_range=time_range if isinstance(time_range, dict) else None,
        cluster_id=cluster["cluster_id"],
        representative_ku_id=cluster.get("representative_ku_id"),
        member_ku_ids=list(cluster.get("member_ku_ids", [])),
        source_doc_ids=list(cluster.get("source_doc_ids", [])),
    )


def _timeline_event_from_unit(unit: dict[str, Any]) -> TimelineEvent:
    time_payload = unit.get("time") or {}
    date_value = time_payload.get("event_time") or time_payload.get("published_at")
    return TimelineEvent(
        event_id=unit["ku_id"],
        event_source="knowledge_unit",
        event_type=unit["unit_type"],
        title=unit["summary"],
        summary=unit["summary"],
        date=date_value,
        time_range=None,
        cluster_id=unit.get("cluster_id"),
        representative_ku_id=unit["ku_id"],
        member_ku_ids=[unit["ku_id"]],
        source_doc_ids=[unit.get("source", {}).get("doc_id")] if unit.get("source", {}).get("doc_id") else [],
    )


def _build_timeline_events(
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
) -> list[TimelineEvent]:
    clusters_by_id = {
        cluster["cluster_id"]: cluster
        for cluster in event_clusters
        if cluster.get("cluster_id")
    }
    events: list[TimelineEvent] = []
    seen_clusters: set[str] = set()

    for unit in knowledge_units:
        cluster_id = unit.get("cluster_id")
        if cluster_id and cluster_id in clusters_by_id:
            if cluster_id in seen_clusters:
                continue
            seen_clusters.add(cluster_id)
            events.append(_timeline_event_from_cluster(clusters_by_id[cluster_id]))
            continue
        events.append(_timeline_event_from_unit(unit))

    for cluster in event_clusters:
        cluster_id = cluster.get("cluster_id")
        if not cluster_id or cluster_id in seen_clusters:
            continue
        seen_clusters.add(cluster_id)
        events.append(_timeline_event_from_cluster(cluster))

    return sorted(
        events,
        key=lambda event: (_parse_anchor(event.date) or datetime.min, event.event_id),
    )


def _build_entity_timeline_payload(
    raw_result: dict[str, Any],
    target_entity: str | None,
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> EntityTimelinePayload:
    return EntityTimelinePayload(
        target_entity=target_entity,
        time_range=raw_result.get("query", {}).get("time_range"),
        timeline_events=_build_timeline_events(knowledge_units, event_clusters),
        supporting_evidence=supporting_evidence,
    )


def _build_focus_event_types(
    raw_result: dict[str, Any],
    event_clusters: list[dict[str, Any]],
    knowledge_units: list[dict[str, Any]],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in (
        *(raw_result.get("query", {}).get("filters", {}).get("event_types") or []),
        *(cluster.get("cluster_type") for cluster in event_clusters),
        *(unit.get("unit_type") for unit in knowledge_units),
    ):
        if not isinstance(candidate, str):
            continue
        value = candidate.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _build_event_analysis_payload(
    raw_result: dict[str, Any],
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    sorted_clusters: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> EventAnalysisPayload:
    return EventAnalysisPayload(
        focus_event_types=_build_focus_event_types(raw_result, event_clusters, knowledge_units),
        event_clusters=sorted_clusters,
        involved_entities=entities,
        supporting_evidence=supporting_evidence,
    )


def _normalize_relationship_paths(graph: dict[str, Any]) -> list[RelationshipPath]:
    raw_paths = graph.get("paths", [])
    if not isinstance(raw_paths, list):
        return []
    normalized: list[RelationshipPath] = []
    for path in raw_paths:
        if not isinstance(path, dict):
            continue
        normalized.append(
            RelationshipPath(
                path_type=str(path.get("path_type", "")),
                start_entity_id=path.get("start_entity_id"),
                start_entity_name=path.get("start_entity_name"),
                cluster_id=path.get("cluster_id"),
                cluster_title=path.get("cluster_title"),
                cluster_type=path.get("cluster_type"),
                neighbor_entity_id=path.get("neighbor_entity_id"),
                neighbor_entity_name=path.get("neighbor_entity_name"),
                member_ku_ids=list(path.get("member_ku_ids", [])),
            )
        )
    return normalized


def _build_relationship_graph(graph_data: dict[str, Any]) -> RelationshipGraph:
    if not isinstance(graph_data, dict):
        return RelationshipGraph()
    return RelationshipGraph(
        enabled=bool(graph_data.get("enabled", False)),
        used=bool(graph_data.get("used", False)),
        nodes=list(graph_data.get("nodes", [])),
        edges=list(graph_data.get("edges", [])),
        paths=list(graph_data.get("paths", [])),
        summary=dict(graph_data.get("summary", {})),
    )


def _filter_related_entities(
    entities: list[dict[str, Any]],
    *,
    target_entity: str | None,
    allowed_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    related_entities: list[dict[str, Any]] = []
    for entity in entities:
        if _is_target_entity(entity, target_entity):
            continue
        entity_id = entity.get("entity_id")
        if allowed_ids is not None and entity_id not in allowed_ids:
            continue
        related_entities.append(entity)
    return related_entities


def _build_relationship_query_payload(
    raw_result: dict[str, Any],
    target_entity: str | None,
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> RelationshipQueryPayload:
    graph_data = raw_result.get("graph", {})
    if not isinstance(graph_data, dict):
        graph_data = {}
    graph = _build_relationship_graph(graph_data)

    query_source = raw_result.get("source")
    if query_source != "knowledge_base" or not _verification_passed(raw_result.get("verification")):
        return RelationshipQueryPayload(
            target_entity=target_entity,
            graph=graph,
            supporting_evidence=supporting_evidence,
        )

    relationship_paths = _normalize_relationship_paths(graph_data)

    # Build both ID sets in a single pass
    related_entity_ids: set[str] = set()
    cluster_ids: set[str] = set()
    for path in relationship_paths:
        if path.neighbor_entity_id:
            related_entity_ids.add(path.neighbor_entity_id)
        if path.cluster_id:
            cluster_ids.add(path.cluster_id)

    related_entities = _filter_related_entities(
        entities,
        target_entity=target_entity,
        allowed_ids=related_entity_ids,
    )

    related_event_clusters = [
        cluster for cluster in event_clusters if cluster.get("cluster_id") in cluster_ids
    ]

    return RelationshipQueryPayload(
        target_entity=target_entity,
        related_entities=related_entities,
        related_event_clusters=related_event_clusters,
        relationship_paths=relationship_paths,
        graph=graph,
        supporting_evidence=supporting_evidence,
    )


def _build_payload(
    raw_result: dict[str, Any],
    skill_type: SkillType,
    *,
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    target_entity: str | None,
    sorted_clusters: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> EntityOverviewPayload | EntityTimelinePayload | EventAnalysisPayload | RelationshipQueryPayload:
    if skill_type == "entity_overview":
        return _build_entity_overview_payload(
            entities=entities,
            target_entity=target_entity,
            sorted_clusters=sorted_clusters,
            supporting_evidence=supporting_evidence,
        )
    if skill_type == "entity_timeline":
        return _build_entity_timeline_payload(
            raw_result=raw_result,
            target_entity=target_entity,
            knowledge_units=knowledge_units,
            event_clusters=event_clusters,
            supporting_evidence=supporting_evidence,
        )
    if skill_type == "event_analysis":
        return _build_event_analysis_payload(
            raw_result=raw_result,
            knowledge_units=knowledge_units,
            event_clusters=event_clusters,
            entities=entities,
            sorted_clusters=sorted_clusters,
            supporting_evidence=supporting_evidence,
        )
    return _build_relationship_query_payload(
        raw_result=raw_result,
        target_entity=target_entity,
        event_clusters=sorted_clusters,
        entities=entities,
        supporting_evidence=supporting_evidence,
    )


def _error_contract(errors: list[str], raw_result: dict[str, Any] | None = None) -> SkillContract:
    """Build an error response contract with optional raw result context."""
    return SkillContract(
        ok=False,
        skill_type=None,
        source=raw_result.get("source") if raw_result else None,
        query=dict(raw_result.get("query", {})) if raw_result else {},
        summary=_build_summary(raw_result) if raw_result else SkillSummary(),
        capabilities=_build_capabilities(raw_result or {}, skill_type=None),
        payload=None,
        verification=dict(raw_result.get("verification", {})) if raw_result else {},
        errors=errors,
    )


def run_skill_query(
    raw_query: str = "",
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
) -> dict[str, Any]:
    """Run the stable skill-facing retrieval contract over the knowledge foundation."""
    raw_result = run_pipeline(
        raw_query=raw_query,
        articles=articles,
        graph_enabled=graph_enabled,
    )
    if "error" in raw_result:
        return _error_contract(["missing query input"]).model_dump(mode="json")

    intent = raw_result.get("query", {}).get("intent")
    skill_type = SUPPORTED_INTENTS.get(intent)
    if skill_type is None:
        return _error_contract([f"unsupported_intent:{intent}"], raw_result).model_dump(mode="json")

    # Extract common data once to avoid repeated dict access
    knowledge_units = raw_result.get("knowledge_units", [])
    event_clusters = raw_result.get("event_clusters", [])
    entities = raw_result.get("entities", [])
    target_entity = _target_entity(raw_result)
    sorted_clusters = _sort_clusters_desc(event_clusters)
    supporting_evidence = _normalize_supporting_evidence(knowledge_units)

    payload = _build_payload(
        raw_result,
        skill_type,
        knowledge_units=knowledge_units,
        event_clusters=event_clusters,
        entities=entities,
        target_entity=target_entity,
        sorted_clusters=sorted_clusters,
        supporting_evidence=supporting_evidence,
    )

    contract = SkillContract(
        ok=_contract_ok(raw_result),
        skill_type=skill_type,
        source=raw_result.get("source"),
        query=dict(raw_result.get("query", {})),
        summary=SkillSummary(
            knowledge_unit_count=len(knowledge_units),
            entity_count=len(entities),
            event_cluster_count=len(event_clusters),
            total_count=int(raw_result.get("total_count", 0)),
        ),
        capabilities=_build_capabilities(raw_result, skill_type=skill_type),
        payload=payload,
        verification=dict(raw_result.get("verification", {})),
        errors=list(raw_result.get("errors", [])),
    )
    return contract.model_dump(mode="json")
