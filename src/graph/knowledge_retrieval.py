"""
Knowledge-graph retrieval over Entity -> INVOLVED_IN -> EventCluster.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, ContextManager, Iterable, Protocol, TypeVar, cast

from neo4j.exceptions import (
    ServiceUnavailable,
    SessionExpired,
    ReadServiceUnavailable,
    ConnectionAcquisitionTimeoutError,
    DatabaseUnavailable,
)

from src.entities import Entity, EntityRepository
from src.event_merging import EventCluster, EventClusterRepository
from src.graph.connection import get_connection
from src.schemas.query import StructuredQuery

logger = logging.getLogger(__name__)

DEFAULT_HOPS = 1
MAX_HOPS = 5
MAX_PATH_RESULTS = 50

# 瞬时连接异常：并发下偶发的服务抖动，短重试 1 次通常可恢复。
_TRANSIENT_EXC: tuple[type[BaseException], ...] = (
    ServiceUnavailable,
    SessionExpired,
    ReadServiceUnavailable,
    ConnectionAcquisitionTimeoutError,
    DatabaseUnavailable,
)
_TRANSIENT_RETRY_DELAY = 0.2
_TRANSIENT_MAX_RETRIES = 1

T = TypeVar("T")


def _run_with_transient_retry(
    session_ctx: ContextManager[Any],
    fn: Callable[[Any], T],
) -> T:
    """Run a Cypher read with one short retry on transient connection errors.

    Keeps existing degrading behavior for non-transient failures: callers wrap
    the whole call in try/except and produce a degraded result.
    """
    last_exc: BaseException | None = None
    for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
        try:
            with session_ctx as session:
                return fn(session)
        except _TRANSIENT_EXC as exc:
            last_exc = exc
            if attempt < _TRANSIENT_MAX_RETRIES:
                logger.warning(
                    "Neo4j transient error (%s), retrying once", type(exc).__name__
                )
                time.sleep(_TRANSIENT_RETRY_DELAY)
                continue
            raise
    # Unreachable: loop either returns or raises; satisfy type checker.
    assert last_exc is not None
    raise last_exc


class GraphSessionLike(Protocol):
    def run(self, query: str, **params: object) -> object:
        ...


class GraphConnectionLike(Protocol):
    def session(self) -> ContextManager[GraphSessionLike]:
        ...


@dataclass
class GraphClusterSummary:
    """Lightweight cluster overview for tier-1 delivery."""

    cluster_id: str
    title: str
    cluster_type: str
    member_count: int
    neighbor_entity_names: list[str]
    hit_reasons: list[str]


@dataclass
class GraphRetrievalResult:
    used: bool
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    paths: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    expanded_entities: list[Entity] = field(default_factory=list)
    expanded_clusters: list[EventCluster] = field(default_factory=list)
    cluster_summaries: list[GraphClusterSummary] = field(default_factory=list)
    hit_reasons: dict[str, list[str]] = field(default_factory=dict)
    candidate_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def expanded_cluster_count(self) -> int:
        return len(self.expanded_clusters)

    @property
    def expanded_entity_count(self) -> int:
        return len(self.expanded_entities)

    def to_graph_dict(self, enabled: bool) -> dict[str, Any]:
        base: dict[str, Any] = {
            "enabled": enabled,
            "used": self.used,
            "summary": self.summary,
        }
        if self.cluster_summaries:
            base["clusters_overview"] = [
                {
                    "cluster_id": s.cluster_id,
                    "title": s.title,
                    "cluster_type": s.cluster_type,
                    "member_count": s.member_count,
                    "neighbor_entities": s.neighbor_entity_names,
                    "hit_reasons": s.hit_reasons,
                }
                for s in self.cluster_summaries
            ]
        if self.nodes or self.edges or self.paths:
            base["nodes"] = self.nodes
            base["edges"] = self.edges
            base["paths"] = self.paths
        return base

    @classmethod
    def empty(
        cls,
        *,
        start_entities: list[Entity] | None = None,
    ) -> GraphRetrievalResult:
        return cls(
            used=False,
            summary=_build_summary(start_entities or [], [], [], expanded=False),
        )


def _build_summary(
    start_entities: list[Entity],
    clusters: list[EventCluster],
    expanded_entities: list[Entity],
    *,
    expanded: bool,
) -> dict[str, Any]:
    return {
        "start_entities": [
            {
                "entity_id": entity.entity_id,
                "name": entity.canonical_name,
            }
            for entity in start_entities
        ],
        "event_cluster_count": len(clusters),
        "expanded_entity_count": len(expanded_entities),
        "expanded": expanded,
    }


def _build_summary_from_counts(
    start_entities: list[Entity],
    *,
    cluster_count: int,
    entity_count: int,
    expanded: bool,
) -> dict[str, Any]:
    return {
        "start_entities": [
            {
                "entity_id": entity.entity_id,
                "name": entity.canonical_name,
            }
            for entity in start_entities
        ],
        "event_cluster_count": cluster_count,
        "expanded_entity_count": entity_count,
        "expanded": expanded,
    }


def _build_path_summary(
    entity_a: Entity,
    entity_b: Entity,
    *,
    cluster_count: int = 0,
    entity_count: int = 0,
    path_count: int = 0,
) -> dict[str, Any]:
    return {
        "start_entities": [{"entity_id": entity_a.entity_id, "name": entity_a.canonical_name}],
        "target_entity": {"entity_id": entity_b.entity_id, "name": entity_b.canonical_name},
        "event_cluster_count": cluster_count,
        "expanded_entity_count": entity_count,
        "path_count": path_count,
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class KnowledgeGraphRetriever:
    """Formal graph retrieval service for the current knowledge graph model."""

    def __init__(
        self,
        *,
        db_path: str = "data/news.db",
        connection: GraphConnectionLike | None = None,
        entity_repo: EntityRepository | None = None,
        cluster_repo: EventClusterRepository | None = None,
    ) -> None:
        self.connection = connection or get_connection()
        self.entity_repo = entity_repo or EntityRepository(db_path)
        self.cluster_repo = cluster_repo or EventClusterRepository(db_path)

    def search(
        self,
        structured_query: StructuredQuery,
        *,
        start_entities: list[Entity],
        summary_only: bool = False,
    ) -> GraphRetrievalResult:
        if not start_entities:
            return GraphRetrievalResult.empty(start_entities=[])

        effective_hops = max(min(structured_query.hops, MAX_HOPS), 1)
        max_edges = 2 * effective_hops - 1  # N Entity-hops = 2N-1 max edges to farthest EC

        try:
            records = _run_with_transient_retry(
                self.connection.session(),
                lambda session: list(
                    cast(
                        Iterable[Any],
                        session.run(
                            f"""
                            MATCH path = (start:Entity)-[:INVOLVED_IN*1..{max_edges}]-(cluster:EventCluster)
                            WHERE start.id IN $start_entity_ids
                            WITH start, cluster
                            OPTIONAL MATCH (cluster)<-[:INVOLVED_IN]-(neighbor:Entity)
                            RETURN
                                start.id AS start_entity_id,
                                cluster.id AS cluster_id,
                                cluster.cluster_type AS cluster_type,
                                cluster.title AS cluster_title,
                                cluster.summary AS cluster_summary,
                                cluster.primary_entity_id AS cluster_primary_entity_id,
                                cluster.member_ku_ids AS member_ku_ids,
                                cluster.source_doc_ids AS source_doc_ids,
                                cluster.conflict_status AS conflict_status,
                                cluster.representative_ku_id AS representative_ku_id,
                                cluster.member_count AS member_count,
                                cluster.source_count AS source_count,
                                cluster.time_range_json AS time_range_json,
                                neighbor.id AS neighbor_entity_id
                            """,
                            start_entity_ids=[
                                entity.entity_id for entity in start_entities
                            ],
                        ),
                    )
                ),
            )
        except Exception as exc:
            return GraphRetrievalResult(
                used=False,
                errors=[f"图谱服务不可用（{type(exc).__name__}），已降级为纯文本检索"],
                summary=_build_summary(start_entities, [], [], expanded=False),
            )

        cluster_rows = self._group_cluster_rows(records)
        candidate_count = len(cluster_rows)
        if not cluster_rows:
            return GraphRetrievalResult(
                used=True,
                candidate_count=0,
                summary=_build_summary(start_entities, [], [], expanded=False),
            )

        filtered_cluster_ids = [
            cluster_id
            for cluster_id, row in cluster_rows.items()
            if self._matches_filters(row, structured_query)
        ]

        if summary_only:
            return self._build_summary_result(
                start_entities=start_entities,
                cluster_rows=cluster_rows,
                filtered_cluster_ids=filtered_cluster_ids,
                candidate_count=candidate_count,
            )

        expanded_clusters = self.cluster_repo.get_by_ids(filtered_cluster_ids)
        cluster_map = {cluster.cluster_id: cluster for cluster in expanded_clusters}
        if not cluster_map:
            return GraphRetrievalResult(
                used=True,
                candidate_count=candidate_count,
                summary=_build_summary(start_entities, [], [], expanded=False),
            )

        start_ids = {entity.entity_id for entity in start_entities}
        expanded_entity_ids = sorted(
            {
                neighbor_id
                for cluster_id in filtered_cluster_ids
                for neighbor_id in cluster_rows[cluster_id]["neighbor_entity_ids"]
                if neighbor_id and neighbor_id not in start_ids
            }
        )
        expanded_entities = self.entity_repo.get_by_ids(expanded_entity_ids)
        expanded_entity_map = {entity.entity_id: entity for entity in expanded_entities}
        start_entity_map = {entity.entity_id: entity for entity in start_entities}

        nodes = self._build_nodes(start_entities, expanded_clusters, expanded_entities)
        edges = self._build_edges(cluster_rows, filtered_cluster_ids, start_entity_map, expanded_entity_map)
        paths, hit_reasons = self._build_paths(
            cluster_rows,
            filtered_cluster_ids,
            start_entities=start_entities,
            expanded_clusters=cluster_map,
            expanded_entities=expanded_entity_map,
        )
        expanded = bool(filtered_cluster_ids or expanded_entity_ids)
        return GraphRetrievalResult(
            used=True,
            nodes=nodes,
            edges=edges,
            paths=paths,
            summary=_build_summary(
                start_entities,
                list(cluster_map.values()),
                expanded_entities,
                expanded=expanded,
            ),
            expanded_entities=expanded_entities,
            expanded_clusters=list(cluster_map.values()),
            hit_reasons=hit_reasons,
            candidate_count=candidate_count,
        )

    def _build_summary_result(
        self,
        *,
        start_entities: list[Entity],
        cluster_rows: dict[str, dict[str, Any]],
        filtered_cluster_ids: list[str],
        candidate_count: int,
    ) -> GraphRetrievalResult:
        """Build a lightweight result with cluster summaries instead of full objects."""
        start_ids = {entity.entity_id for entity in start_entities}
        neighbor_ids_per_cluster: dict[str, set[str]] = {}

        for cluster_id in filtered_cluster_ids:
            neighbor_ids_per_cluster[cluster_id] = {
                nid
                for nid in cluster_rows[cluster_id]["neighbor_entity_ids"]
                if nid and nid not in start_ids
            }

        all_neighbor_ids = sorted(
            {nid for ids in neighbor_ids_per_cluster.values() for nid in ids}
        )
        neighbor_names = self._resolve_entity_names(all_neighbor_ids)

        summaries: list[GraphClusterSummary] = []
        hit_reasons: dict[str, list[str]] = {}

        for cluster_id in filtered_cluster_ids:
            row = cluster_rows[cluster_id]
            neighbor_names_for_cluster = sorted(
                neighbor_names.get(nid, nid)
                for nid in neighbor_ids_per_cluster[cluster_id]
            )
            seed_reasons = sorted(
                f"seed_entity:{e.canonical_name}"
                for e in start_entities
                if e.entity_id in row["start_entity_ids"]
            )
            summaries.append(
                GraphClusterSummary(
                    cluster_id=cluster_id,
                    title=row.get("cluster_title", ""),
                    cluster_type=row.get("cluster_type", ""),
                    member_count=row.get("member_count", 0),
                    neighbor_entity_names=neighbor_names_for_cluster,
                    hit_reasons=seed_reasons,
                )
            )
            hit_reasons[cluster_id] = seed_reasons

        return GraphRetrievalResult(
            used=True,
            cluster_summaries=summaries,
            summary=_build_summary_from_counts(
                start_entities,
                cluster_count=len(filtered_cluster_ids),
                entity_count=len(all_neighbor_ids),
                expanded=bool(filtered_cluster_ids),
            ),
            hit_reasons=hit_reasons,
            candidate_count=candidate_count,
        )

    def expand_clusters(
        self,
        cluster_ids: list[str],
        *,
        start_entities: list[Entity] | None = None,
    ) -> GraphRetrievalResult:
        """Load full details for specific clusters (Tier-2 expansion)."""
        if not cluster_ids:
            return GraphRetrievalResult(
                used=True,
                candidate_count=0,
                summary=_build_summary(start_entities or [], [], [], expanded=False),
            )

        expanded_clusters = self.cluster_repo.get_by_ids(cluster_ids)
        cluster_map = {c.cluster_id: c for c in expanded_clusters}

        if not cluster_map:
            return GraphRetrievalResult(
                used=True,
                candidate_count=0,
                summary=_build_summary(start_entities or [], [], [], expanded=False),
            )

        all_entity_ids: set[str] = set()
        for cluster in expanded_clusters:
            all_entity_ids.update(cluster.entity_ids)

        start_ids = {e.entity_id for e in (start_entities or [])}
        neighbor_ids = sorted(all_entity_ids - start_ids)
        expanded_entities = self.entity_repo.get_by_ids(neighbor_ids)
        expanded_entity_map = {e.entity_id: e for e in expanded_entities}
        start_entity_map = {e.entity_id: e for e in (start_entities or [])}

        cluster_rows = {
            c.cluster_id: {
                "start_entity_ids": {eid for eid in c.entity_ids if eid in start_ids},
                "neighbor_entity_ids": {eid for eid in c.entity_ids if eid not in start_ids},
            }
            for c in expanded_clusters
        }

        nodes = self._build_nodes(start_entities or [], expanded_clusters, expanded_entities)
        edges = self._build_edges(cluster_rows, list(cluster_map.keys()), start_entity_map, expanded_entity_map)
        paths, hit_reasons = self._build_paths(
            cluster_rows,
            list(cluster_map.keys()),
            start_entities=start_entities or [],
            expanded_clusters=cluster_map,
            expanded_entities=expanded_entity_map,
        )

        return GraphRetrievalResult(
            used=True,
            nodes=nodes,
            edges=edges,
            paths=paths,
            summary=_build_summary(
                start_entities or [],
                list(cluster_map.values()),
                expanded_entities,
                expanded=True,
            ),
            expanded_entities=expanded_entities,
            expanded_clusters=list(cluster_map.values()),
            hit_reasons=hit_reasons,
            candidate_count=len(expanded_clusters),
        )

    def _resolve_entity_names(self, entity_ids: list[str]) -> dict[str, str]:
        """Resolve entity IDs to names without loading full objects."""
        if not entity_ids:
            return {}
        entities = self.entity_repo.get_by_ids(entity_ids)
        return {e.entity_id: e.canonical_name for e in entities}

    def _group_cluster_rows(self, records: list[Any]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for record in records:
            cluster_id = record["cluster_id"]
            if cluster_id is None:
                continue
            row = grouped.setdefault(
                cluster_id,
                {
                    "start_entity_ids": set(),
                    "neighbor_entity_ids": set(),
                    "cluster_type": record["cluster_type"],
                    "cluster_title": record.get("cluster_title"),
                    "member_count": record.get("member_count", 0),
                    "time_range_json": record["time_range_json"],
                },
            )
            if record["start_entity_id"]:
                row["start_entity_ids"].add(record["start_entity_id"])
            if record["neighbor_entity_id"]:
                row["neighbor_entity_ids"].add(record["neighbor_entity_id"])
        return grouped

    def _matches_filters(self, row: dict[str, Any], structured_query: StructuredQuery) -> bool:
        event_types = structured_query.filters.event_types or []
        if event_types and row["cluster_type"] not in event_types:
            return False
        if structured_query.time_range is None:
            return True
        return self._matches_time_range(row.get("time_range_json"), structured_query)

    def _matches_time_range(
        self,
        time_range_json: str | None,
        structured_query: StructuredQuery,
    ) -> bool:
        if structured_query.time_range is None:
            return True
        if not time_range_json:
            return False
        try:
            payload = json.loads(time_range_json)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        cluster_start = _parse_date(payload.get("start"))
        cluster_end = _parse_date(payload.get("end"))
        if cluster_start is None or cluster_end is None:
            return False
        request_start = structured_query.time_range.start
        request_end = structured_query.time_range.end
        if request_start > request_end:
            request_start, request_end = request_end, request_start
        return cluster_start <= request_end and request_start <= cluster_end

    def _build_nodes(
        self,
        start_entities: list[Entity],
        clusters: list[EventCluster],
        expanded_entities: list[Entity],
    ) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for entity in start_entities:
            nodes.append(
                {
                    "id": entity.entity_id,
                    "type": "Entity",
                    "name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "is_start": True,
                }
            )
        for cluster in clusters:
            nodes.append(
                {
                    "id": cluster.cluster_id,
                    "type": "EventCluster",
                    "name": cluster.title,
                    "cluster_type": cluster.cluster_type,
                    "member_ku_ids": cluster.member_ku_ids,
                }
            )
        for entity in expanded_entities:
            nodes.append(
                {
                    "id": entity.entity_id,
                    "type": "Entity",
                    "name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "is_start": False,
                }
            )
        return nodes

    def _build_edges(
        self,
        cluster_rows: dict[str, dict[str, Any]],
        filtered_cluster_ids: list[str],
        start_entities: dict[str, Entity],
        expanded_entities: dict[str, Entity],
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for cluster_id in filtered_cluster_ids:
            row = cluster_rows[cluster_id]
            for entity_id in sorted(row["start_entity_ids"]):
                if entity_id not in start_entities:
                    continue
                key = (entity_id, cluster_id)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "source": entity_id,
                        "target": cluster_id,
                        "type": "INVOLVED_IN",
                        "direction": "entity_to_cluster",
                    }
                )
            for entity_id in sorted(row["neighbor_entity_ids"]):
                if entity_id not in expanded_entities:
                    continue
                key = (entity_id, cluster_id)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "source": entity_id,
                        "target": cluster_id,
                        "type": "INVOLVED_IN",
                        "direction": "entity_to_cluster",
                    }
                )
        return edges

    def _build_paths(
        self,
        cluster_rows: dict[str, dict[str, Any]],
        filtered_cluster_ids: list[str],
        *,
        start_entities: list[Entity],
        expanded_clusters: dict[str, EventCluster],
        expanded_entities: dict[str, Entity],
    ) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
        start_entity_map = {entity.entity_id: entity for entity in start_entities}
        paths: list[dict[str, Any]] = []
        hit_reasons: dict[str, list[str]] = {}

        for cluster_id in filtered_cluster_ids:
            cluster = expanded_clusters[cluster_id]
            row = cluster_rows[cluster_id]
            for entity_id in sorted(row["start_entity_ids"]):
                entity = start_entity_map.get(entity_id)
                if entity is None:
                    continue
                paths.append(
                    {
                        "path_type": "Entity->EventCluster",
                        "start_entity_id": entity.entity_id,
                        "start_entity_name": entity.canonical_name,
                        "cluster_id": cluster.cluster_id,
                        "cluster_title": cluster.title,
                        "cluster_type": cluster.cluster_type,
                        "member_ku_ids": cluster.member_ku_ids,
                    }
                )
                hit_reasons.setdefault(cluster.cluster_id, []).append(
                    f"seed_entity:{entity.canonical_name}"
                )
            for neighbor_id in sorted(row["neighbor_entity_ids"]):
                neighbor = expanded_entities.get(neighbor_id)
                if neighbor is None:
                    continue
                for entity_id in sorted(row["start_entity_ids"]):
                    entity = start_entity_map.get(entity_id)
                    if entity is None:
                        continue
                    paths.append(
                        {
                            "path_type": "Entity->EventCluster->Entity",
                            "start_entity_id": entity.entity_id,
                            "start_entity_name": entity.canonical_name,
                            "cluster_id": cluster.cluster_id,
                            "cluster_title": cluster.title,
                            "neighbor_entity_id": neighbor.entity_id,
                            "neighbor_entity_name": neighbor.canonical_name,
                            "member_ku_ids": cluster.member_ku_ids,
                        }
                    )
                    hit_reasons.setdefault(neighbor.entity_id, []).append(
                        f"co_involved_via:{cluster.cluster_id}"
                    )
        return paths, hit_reasons

    def search_relationship_path(
        self,
        *,
        entity_a: Entity,
        entity_b: Entity,
        max_hops: int = 3,
    ) -> GraphRetrievalResult:
        """Find all paths between two entities in the bipartite graph.

        Returns paths connecting entity_a to entity_b within max_hops Entity-to-Entity distance.
        Each path alternates between Entity and EventCluster nodes.
        """
        if entity_a.entity_id == entity_b.entity_id:
            return GraphRetrievalResult(
                used=True,
                candidate_count=0,
                summary=_build_path_summary(entity_a, entity_b),
            )

        effective_hops = max(min(max_hops, MAX_HOPS), 1)
        max_edges = 2 * effective_hops  # N Entity-hops = 2N max edges for A-to-B path

        try:
            records = _run_with_transient_retry(
                self.connection.session(),
                lambda session: list(
                    cast(
                        Iterable[Any],
                        session.run(
                            f"""
                            MATCH path = (a:Entity {{id: $entity_a_id}})-[:INVOLVED_IN*1..{max_edges}]-(b:Entity {{id: $entity_b_id}})
                            WHERE a.id <> b.id
                            RETURN
                                [n IN nodes(path) | {{
                                    id: n.id,
                                    type: CASE WHEN n:Entity THEN 'Entity' ELSE 'EventCluster' END,
                                    name: coalesce(n.name, n.title),
                                    entity_type: n.entity_type,
                                    cluster_type: n.cluster_type
                                }}] AS path_nodes,
                                [r IN relationships(path) | type(r)] AS path_rels,
                                length(path) AS path_length
                            ORDER BY path_length
                            LIMIT {MAX_PATH_RESULTS}
                            """,
                            entity_a_id=entity_a.entity_id,
                            entity_b_id=entity_b.entity_id,
                        ),
                    )
                ),
            )
        except Exception as exc:
            return GraphRetrievalResult(
                used=False,
                errors=[f"图谱服务不可用（{type(exc).__name__}），关系路径查询需要图谱服务"],
                summary=_build_path_summary(entity_a, entity_b),
            )

        if not records:
            return GraphRetrievalResult(
                used=True,
                candidate_count=0,
                summary=_build_path_summary(entity_a, entity_b),
            )

        nodes_map: dict[str, dict[str, Any]] = {}
        edges_set: set[tuple[str, str]] = set()
        all_paths: list[dict[str, Any]] = []
        expanded_entity_ids: set[str] = set()
        expanded_cluster_ids: set[str] = set()

        for record in records:
            path_nodes = record["path_nodes"]
            path_rels = record["path_rels"]
            path_length = record["path_length"]

            for node in path_nodes:
                node_id = node["id"]
                if node_id not in nodes_map:
                    nodes_map[node_id] = {
                        "id": node_id,
                        "type": node["type"],
                        "name": node["name"],
                        **({"entity_type": node["entity_type"]} if node["type"] == "Entity" else {}),
                        **({"cluster_type": node["cluster_type"]} if node["type"] == "EventCluster" else {}),
                    }
                if node["type"] == "Entity":
                    expanded_entity_ids.add(node_id)
                else:
                    expanded_cluster_ids.add(node_id)

            for i in range(len(path_nodes) - 1):
                edge = (path_nodes[i]["id"], path_nodes[i + 1]["id"])
                edges_set.add(edge)

            all_paths.append({
                "path_type": "relationship_path",
                "path_length": path_length,
                "path_nodes": path_nodes,
                "path_rels": path_rels,
                "entity_hops": (path_length // 2) + 1 if path_length >= 2 else 0,
            })

        expanded_entities = self.entity_repo.get_by_ids(list(expanded_entity_ids))
        expanded_clusters = self.cluster_repo.get_by_ids(list(expanded_cluster_ids))

        entity_map = {e.entity_id: e for e in expanded_entities}
        cluster_map = {c.cluster_id: c for c in expanded_clusters}

        nodes: list[dict[str, Any]] = []
        for node_id, node in nodes_map.items():
            if node["type"] == "Entity" and node_id in entity_map:
                entity = entity_map[node_id]
                nodes.append({
                    "id": entity.entity_id,
                    "type": "Entity",
                    "name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "is_start": entity.entity_id == entity_a.entity_id,
                    "is_target": entity.entity_id == entity_b.entity_id,
                })
            elif node["type"] == "EventCluster" and node_id in cluster_map:
                cluster = cluster_map[node_id]
                nodes.append({
                    "id": cluster.cluster_id,
                    "type": "EventCluster",
                    "name": cluster.title,
                    "cluster_type": cluster.cluster_type,
                    "member_ku_ids": cluster.member_ku_ids,
                })

        edges: list[dict[str, Any]] = []
        for source, target in edges_set:
            edges.append({
                "source": source,
                "target": target,
                "type": "INVOLVED_IN",
            })

        return GraphRetrievalResult(
            used=True,
            nodes=nodes,
            edges=edges,
            paths=all_paths,
            summary=_build_path_summary(
                entity_a, entity_b,
                cluster_count=len(expanded_clusters),
                entity_count=len(expanded_entities),
                path_count=len(all_paths),
            ),
            expanded_entities=expanded_entities,
            expanded_clusters=expanded_clusters,
            candidate_count=len(expanded_clusters),
        )
