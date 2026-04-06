"""
Skill-facing retrieval adapter over the raw retrieval pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.entities import entity_matches_query_name
from src.intent.models import IntentType
from src.orchestration.graph import run_pipeline
from src.risk.patterns import PatternDetector, PatternType
from src.risk.weights import get_risk_level
from src.skills.models import (
    EntityOverviewPayload,
    EntityTimelinePayload,
    EventAnalysisPayload,
    GuaranteeAnalysisPayload,
    GuaranteePatternPayload,
    RelationshipGraph,
    RelationshipPath,
    RelationshipQueryPayload,
    RiskAssessmentPayload,
    RiskFactorPayload,
    RiskPathPayload,
    SkillCapabilities,
    SkillContract,
    SkillSummary,
    SkillType,
    SupportingEvidence,
    TimelineEvent,
)


SUPPORTED_INTENTS: dict[str, SkillType] = {
    IntentType.ENTITY_OVERVIEW.value: "entity_overview",
    IntentType.ENTITY_TIMELINE.value: "entity_timeline",
    IntentType.EVENT_ANALYSIS.value: "event_analysis",
    IntentType.RELATIONSHIP_QUERY.value: "relationship_query",
    IntentType.RISK_ASSESSMENT.value: "risk_assessment",
    IntentType.GUARANTEE_ANALYSIS.value: "guarantee_analysis",
}

CLUSTER_TYPE_TO_RISK_FACTOR: dict[str, str] = {
    "debt_default": "DEBT_DEFAULT",
    "equity_pledge": "EQUITY_PLEDGE",
    "legal_suit": "LEGAL_SUIT",
    "real_control_change": "REAL_CONTROL_CHANGE",
    "restructuring": "RESTRUCTURING",
    "policy_sanction": "POLICY_SANCTION",
    "violation": "VIOLATION",
    "fraud": "FRAUD",
}

BASE_RISK_SCORES: dict[str, float] = {
    "debt_default": 0.9,
    "equity_pledge": 0.7,
    "legal_suit": 0.6,
    "real_control_change": 0.5,
    "restructuring": 0.4,
    "policy_sanction": 0.8,
    "violation": 0.7,
    "fraud": 0.9,
}

GUARANTEE_KEYWORDS = ("担保", "保证", "guarantee", "关联担保")
GUARANTOR_ROLE_KEYWORDS = ("guarantor", "guarantee_provider", "担保方", "保证人", "担保人")
GUARANTEED_ROLE_KEYWORDS = ("guaranteed", "guaranteed_party", "debtor", "被担保方", "债务人")


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
    for candidate in (
        cluster.get("time_anchor"),
        time_range.get("end"),
        time_range.get("start"),
    ):
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
    if isinstance(entities, list) and entities and isinstance(entities[0], str):
        return entities[0]
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


def _build_entity_overview_payload(
    entities: list[dict[str, Any]],
    target_entity: str | None,
    sorted_clusters: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> EntityOverviewPayload:
    return EntityOverviewPayload(
        target_entity=target_entity,
        recent_event_clusters=sorted_clusters,
        related_entities=_filter_related_entities(entities, target_entity=target_entity),
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
    filters = raw_result.get("query", {}).get("filters", {})
    if not isinstance(filters, dict):
        filters = {}

    for candidate in (
        *(filters.get("event_types") or []),
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


def _build_risk_assessment_payload(
    raw_result: dict[str, Any],
    target_entity: str | None,
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> RiskAssessmentPayload:
    target_entity_id: str | None = None
    for entity in entities:
        if _is_target_entity(entity, target_entity):
            target_entity_id = entity.get("entity_id")
            break

    graph_data = raw_result.get("graph", {})
    paths = graph_data.get("paths", []) if isinstance(graph_data, dict) else []
    paths_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        if not isinstance(path, dict):
            continue
        cluster_id = path.get("cluster_id")
        if cluster_id:
            paths_by_cluster.setdefault(cluster_id, []).append(path)

    risk_factors: list[RiskFactorPayload] = []
    risk_paths: list[RiskPathPayload] = []
    source_doc_ids: set[str] = set()

    for cluster in event_clusters:
        cluster_type = cluster.get("cluster_type", "")
        factor_type = CLUSTER_TYPE_TO_RISK_FACTOR.get(cluster_type)
        if not factor_type:
            continue

        cluster_id = str(cluster.get("cluster_id", ""))
        base_score = BASE_RISK_SCORES.get(cluster_type, 0.5)
        title = cluster.get("title") or cluster.get("summary") or cluster_id
        cluster_doc_ids = [doc_id for doc_id in cluster.get("source_doc_ids", []) if isinstance(doc_id, str)]
        source_doc_ids.update(cluster_doc_ids)

        risk_factors.append(
            RiskFactorPayload(
                factor_id=f"factor-{cluster_id}",
                factor_type=factor_type,
                factor_score=base_score,
                description=title,
                source_doc_ids=cluster_doc_ids,
                cluster_ids=[cluster_id],
            )
        )

        for path in paths_by_cluster.get(cluster_id, []):
            risk_paths.append(
                RiskPathPayload(
                    source_entity_id=path.get("neighbor_entity_id") or "",
                    source_entity_name=path.get("neighbor_entity_name") or "",
                    source_risk_score=base_score,
                    path_weight=0.8,
                    time_decay=1.0,
                    cluster_id=cluster_id,
                    relation_chain=[path.get("path_type", "INVOLVED_IN")],
                    event_date=cluster.get("time_anchor"),
                )
            )

    total_score = (
        sum(factor.factor_score for factor in risk_factors) / len(risk_factors)
        if risk_factors
        else 0.0
    )

    return RiskAssessmentPayload(
        target_entity=target_entity,
        target_entity_id=target_entity_id,
        total_risk_score=round(total_score, 3),
        risk_level=get_risk_level(total_score),
        risk_factors=risk_factors,
        risk_paths=risk_paths,
        supporting_evidence=supporting_evidence,
        source_doc_ids=sorted(source_doc_ids),
    )


def _normalize_keyword_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _is_guarantee_text(value: Any) -> bool:
    text = _normalize_keyword_text(value)
    return bool(text) and any(keyword in text for keyword in GUARANTEE_KEYWORDS)


def _cluster_title(cluster: dict[str, Any]) -> str:
    return str(cluster.get("title") or cluster.get("summary") or cluster.get("cluster_id") or "")


def _is_guarantee_cluster(cluster: dict[str, Any]) -> bool:
    return any(
        _is_guarantee_text(candidate)
        for candidate in (
            cluster.get("cluster_type"),
            cluster.get("title"),
            cluster.get("summary"),
        )
    )


def _build_entity_lookup(entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        entity["entity_id"]: entity
        for entity in entities
        if isinstance(entity, dict) and entity.get("entity_id")
    }


def _entity_name(
    entity_id: str | None,
    fallback_name: str | None,
    entity_lookup: dict[str, dict[str, Any]],
) -> str:
    if entity_id and entity_id in entity_lookup:
        candidate = entity_lookup[entity_id].get("canonical_name")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    if isinstance(fallback_name, str) and fallback_name.strip():
        return fallback_name.strip()
    return entity_id or ""


def _append_guarantee_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    source_id: str | None,
    source_name: str | None,
    target_id: str | None,
    target_name: str | None,
    cluster: dict[str, Any],
    entity_lookup: dict[str, dict[str, Any]],
    source_doc_ids: list[str] | None = None,
) -> None:
    if not source_id or not target_id or source_id == target_id:
        return
    cluster_id = str(cluster.get("cluster_id") or "")
    edge_key = (source_id, target_id, cluster_id)
    if edge_key in seen:
        return

    seen.add(edge_key)
    doc_ids = source_doc_ids or list(cluster.get("source_doc_ids", []))
    edges.append(
        {
            "source_id": source_id,
            "source_name": _entity_name(source_id, source_name, entity_lookup),
            "target_id": target_id,
            "target_name": _entity_name(target_id, target_name, entity_lookup),
            "cluster_id": cluster.get("cluster_id"),
            "cluster_title": _cluster_title(cluster),
            "source_doc_ids": sorted({doc_id for doc_id in doc_ids if isinstance(doc_id, str) and doc_id}),
        }
    )


def _match_entities_by_roles(unit: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    guarantors: list[dict[str, Any]] = []
    guaranteed: list[dict[str, Any]] = []
    for entity in unit.get("entities", []):
        if not isinstance(entity, dict):
            continue
        role = _normalize_keyword_text(entity.get("role"))
        if any(keyword in role for keyword in GUARANTOR_ROLE_KEYWORDS):
            guarantors.append(entity)
        if any(keyword in role for keyword in GUARANTEED_ROLE_KEYWORDS):
            guaranteed.append(entity)
    return guarantors, guaranteed


def _is_guarantee_relation_hint(hint: dict[str, Any]) -> bool:
    return _is_guarantee_text(hint.get("relation_type"))


def _extract_guarantee_edges(
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    entity_lookup = _build_entity_lookup(entities)

    units_by_cluster_id: dict[str, list[dict[str, Any]]] = {}
    units_by_ku_id: dict[str, dict[str, Any]] = {}
    for unit in knowledge_units:
        if not isinstance(unit, dict):
            continue
        ku_id = unit.get("ku_id")
        if isinstance(ku_id, str) and ku_id:
            units_by_ku_id[ku_id] = unit
        cluster_id = unit.get("cluster_id")
        if isinstance(cluster_id, str) and cluster_id:
            units_by_cluster_id.setdefault(cluster_id, []).append(unit)

    for cluster in event_clusters:
        if not isinstance(cluster, dict) or not _is_guarantee_cluster(cluster):
            continue

        cluster_id = cluster.get("cluster_id")
        cluster_units: list[dict[str, Any]] = []
        if isinstance(cluster_id, str) and cluster_id:
            cluster_units = list(units_by_cluster_id.get(cluster_id, []))
        if not cluster_units:
            for ku_id in cluster.get("member_ku_ids", []):
                if isinstance(ku_id, str) and ku_id in units_by_ku_id:
                    cluster_units.append(units_by_ku_id[ku_id])

        for unit in cluster_units:
            unit_doc_id = unit.get("source", {}).get("doc_id")
            unit_doc_ids = [unit_doc_id] if isinstance(unit_doc_id, str) and unit_doc_id else []

            for hint in unit.get("relation_hints", []):
                if not isinstance(hint, dict) or not _is_guarantee_relation_hint(hint):
                    continue
                _append_guarantee_edge(
                    edges,
                    seen,
                    source_id=hint.get("subject_entity_id"),
                    source_name=None,
                    target_id=hint.get("object_entity_id"),
                    target_name=None,
                    cluster=cluster,
                    entity_lookup=entity_lookup,
                    source_doc_ids=unit_doc_ids,
                )

            guarantors, guaranteed = _match_entities_by_roles(unit)
            for guarantor in guarantors:
                for target in guaranteed:
                    _append_guarantee_edge(
                        edges,
                        seen,
                        source_id=guarantor.get("entity_id"),
                        source_name=guarantor.get("mention"),
                        target_id=target.get("entity_id"),
                        target_name=target.get("mention"),
                        cluster=cluster,
                        entity_lookup=entity_lookup,
                        source_doc_ids=unit_doc_ids,
                    )

        if any(edge.get("cluster_id") == cluster_id for edge in edges):
            continue

        entity_ids = [
            entity_id
            for entity_id in cluster.get("entity_ids", [])
            if isinstance(entity_id, str) and entity_id
        ]
        if len(entity_ids) < 2:
            continue

        source_id = cluster.get("primary_entity_id")
        if not isinstance(source_id, str) or not source_id:
            source_id = entity_ids[0]

        for target_id in entity_ids:
            if target_id == source_id:
                continue
            _append_guarantee_edge(
                edges,
                seen,
                source_id=source_id,
                source_name=None,
                target_id=target_id,
                target_name=None,
                cluster=cluster,
                entity_lookup=entity_lookup,
            )

    return edges


def _pattern_type_value(pattern_type: PatternType) -> str:
    mapping = {
        PatternType.CIRCULAR_GUARANTEE: "circular_guarantee",
        PatternType.CHAIN_GUARANTEE: "chain_guarantee",
        PatternType.MANY_TO_ONE_GUARANTEE: "many_to_one_guarantee",
    }
    return mapping.get(pattern_type, pattern_type.name.lower())


def _canonicalize_cycle(cycle: list[str]) -> tuple[str, ...]:
    rotations: list[tuple[str, ...]] = []
    for values in (cycle, list(reversed(cycle))):
        for index in range(len(values)):
            rotation = tuple(values[index:] + values[:index])
            rotations.append(rotation)
    return min(rotations)


def _find_circular_guarantee_cycles(edges: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        if not source_id or not target_id:
            continue
        adjacency.setdefault(source_id, set()).add(target_id)

    cycles: set[tuple[str, ...]] = set()

    def dfs(start: str, current: str, path: list[str], visited: set[str]) -> None:
        for neighbor in adjacency.get(current, set()):
            if neighbor == start and len(path) >= 3:
                cycles.add(_canonicalize_cycle(path.copy()))
                continue
            if neighbor in visited or len(path) >= 6:
                continue
            visited.add(neighbor)
            path.append(neighbor)
            dfs(start, neighbor, path, visited)
            path.pop()
            visited.remove(neighbor)

    for start in adjacency:
        dfs(start, start, [start], {start})

    return sorted(cycles)


def _detect_guarantee_patterns(edges: list[dict[str, Any]]) -> list[GuaranteePatternPayload]:
    if not edges:
        return []

    detector_edges: list[dict[str, Any]] = []
    entity_names: dict[str, str] = {}
    edge_docs_by_pair: dict[tuple[str, str], set[str]] = {}
    for edge in edges:
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        if not source_id or not target_id:
            continue
        detector_edges.append({"source": source_id, "target": target_id})
        entity_names[source_id] = str(edge.get("source_name") or source_id)
        entity_names[target_id] = str(edge.get("target_name") or target_id)
        edge_docs_by_pair.setdefault((source_id, target_id), set()).update(
            {
                doc_id
                for doc_id in edge.get("source_doc_ids", [])
                if isinstance(doc_id, str) and doc_id
            }
        )

    payloads: list[GuaranteePatternPayload] = []
    for pattern in PatternDetector.detect_all_patterns(detector_edges):
        entity_payloads: list[dict[str, Any]] = []
        entity_ids: set[str] = set()
        for entity in pattern.entities:
            entity_id = entity.get("id")
            if not isinstance(entity_id, str) or not entity_id:
                continue
            entity_ids.add(entity_id)
            item: dict[str, Any] = {
                "entity_id": entity_id,
                "entity_name": entity_names.get(entity_id, entity_id),
            }
            if "role" in entity:
                item["role"] = entity["role"]
            if "position" in entity:
                item["position"] = entity["position"]
            entity_payloads.append(item)

        source_doc_ids: set[str] = set()
        for pair, doc_ids in edge_docs_by_pair.items():
            if pair[0] in entity_ids and pair[1] in entity_ids:
                source_doc_ids.update(doc_ids)

        payloads.append(
            GuaranteePatternPayload(
                pattern_type=_pattern_type_value(pattern.pattern_type),
                risk_level=pattern.risk_level.value,
                entities=entity_payloads,
                description=pattern.description,
                source_doc_ids=sorted(source_doc_ids),
            )
        )

    existing_circular_keys = {
        tuple(sorted(item["entity_id"] for item in payload.entities))
        for payload in payloads
        if payload.pattern_type == "circular_guarantee"
    }
    for cycle in _find_circular_guarantee_cycles(edges):
        cycle_key = tuple(sorted(cycle))
        if cycle_key in existing_circular_keys:
            continue
        source_doc_ids: set[str] = set()
        cycle_names = [entity_names.get(entity_id, entity_id) for entity_id in cycle]
        for index, source_id in enumerate(cycle):
            target_id = cycle[(index + 1) % len(cycle)]
            source_doc_ids.update(edge_docs_by_pair.get((source_id, target_id), set()))
        payloads.append(
            GuaranteePatternPayload(
                pattern_type="circular_guarantee",
                risk_level="CRITICAL",
                entities=[
                    {
                        "entity_id": entity_id,
                        "entity_name": entity_names.get(entity_id, entity_id),
                    }
                    for entity_id in cycle
                ],
                description="Detected circular guarantee: " + " -> ".join([*cycle_names, cycle_names[0]]),
                source_doc_ids=sorted(source_doc_ids),
            )
        )

    return payloads


def _build_guarantee_analysis_payload(
    target_entity: str | None,
    knowledge_units: list[dict[str, Any]],
    event_clusters: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    supporting_evidence: list[SupportingEvidence],
) -> GuaranteeAnalysisPayload:
    guarantee_edges = _extract_guarantee_edges(knowledge_units, event_clusters, entities)
    return GuaranteeAnalysisPayload(
        target_entity=target_entity,
        guarantee_edges=guarantee_edges,
        detected_patterns=_detect_guarantee_patterns(guarantee_edges),
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
) -> EntityOverviewPayload | EntityTimelinePayload | EventAnalysisPayload | RelationshipQueryPayload | RiskAssessmentPayload | GuaranteeAnalysisPayload:
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
    if skill_type == "relationship_query":
        return _build_relationship_query_payload(
            raw_result=raw_result,
            target_entity=target_entity,
            event_clusters=sorted_clusters,
            entities=entities,
            supporting_evidence=supporting_evidence,
        )
    if skill_type == "risk_assessment":
        return _build_risk_assessment_payload(
            raw_result=raw_result,
            target_entity=target_entity,
            event_clusters=event_clusters,
            entities=entities,
            supporting_evidence=supporting_evidence,
        )
    return _build_guarantee_analysis_payload(
        target_entity=target_entity,
        knowledge_units=knowledge_units,
        event_clusters=event_clusters,
        entities=entities,
        supporting_evidence=supporting_evidence,
    )


def _error_contract(errors: list[str], raw_result: dict[str, Any] | None = None) -> SkillContract:
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
