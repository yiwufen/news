"""
Sync Entity and EventCluster views into Neo4j.
"""

from __future__ import annotations

import json
from typing import ContextManager, Protocol, TypedDict

from src.entities import Entity
from src.event_clustering import EventCluster
from src.graph.connection import get_connection


class GraphSessionLike(Protocol):
    def run(self, query: str, **params: object) -> object:
        ...


class GraphConnectionLike(Protocol):
    def session(self) -> ContextManager[GraphSessionLike]:
        ...


class GraphSyncStats(TypedDict):
    entities_created: int
    clusters_created: int
    edges_created: int
    errors: list[str]


class KnowledgeGraphSync:
    """Sync Entity / EventCluster / INVOLVED_IN into Neo4j."""

    def __init__(self, connection: GraphConnectionLike | None = None):
        self.connection = connection or get_connection()

    def sync(self, entities: list[Entity], clusters: list[EventCluster]) -> GraphSyncStats:
        entities_created = 0
        clusters_created = 0
        edges_created = 0
        errors: list[str] = []

        try:
            with self.connection.session() as session:
                session.run(
                    """
                    CREATE CONSTRAINT entity_node_id_unique IF NOT EXISTS
                    FOR (e:Entity) REQUIRE e.id IS UNIQUE
                    """
                )
                session.run(
                    """
                    CREATE CONSTRAINT event_cluster_id_unique IF NOT EXISTS
                    FOR (c:EventCluster) REQUIRE c.id IS UNIQUE
                    """
                )

                for entity in entities:
                    session.run(
                        """
                        MERGE (e:Entity {id: $id})
                        SET e.name = $name,
                            e.entity_type = $entity_type,
                            e.aliases = $aliases,
                            e.primary_identifier = $primary_identifier,
                            e.identifiers_json = $identifiers_json,
                            e.tags = $tags,
                            e.source_ku_ids = $source_ku_ids,
                            e.updated_at = $updated_at
                        """,
                        id=entity.entity_id,
                        name=entity.canonical_name,
                        entity_type=entity.entity_type,
                        aliases=entity.aliases,
                        primary_identifier=next(iter(entity.identifiers.values()), None),
                        identifiers_json=json.dumps(entity.identifiers, ensure_ascii=False),
                        tags=entity.tags,
                        source_ku_ids=entity.source_ku_ids,
                        updated_at=entity.updated_at.isoformat(),
                    )
                    entities_created += 1

                for cluster in clusters:
                    session.run(
                        """
                        MERGE (c:EventCluster {id: $id})
                        SET c.cluster_type = $cluster_type,
                            c.title = $title,
                            c.summary = $summary,
                            c.representative_ku_id = $representative_ku_id,
                            c.member_count = $member_count,
                            c.source_count = $source_count,
                            c.member_ku_ids = $member_ku_ids,
                            c.source_doc_ids = $source_doc_ids,
                            c.time_range_json = $time_range_json,
                            c.summary_variants_json = $summary_variants_json,
                            c.event_time_variants_json = $event_time_variants_json,
                            c.conflict_reasons = $conflict_reasons,
                            c.conflict_status = $conflict_status,
                            c.primary_entity_id = $primary_entity_id,
                            c.updated_at = $updated_at
                        """,
                        id=cluster.cluster_id,
                        cluster_type=cluster.cluster_type,
                        title=cluster.title,
                        summary=cluster.summary,
                        representative_ku_id=cluster.representative_ku_id,
                        member_count=cluster.member_count,
                        source_count=cluster.source_count,
                        member_ku_ids=cluster.member_ku_ids,
                        source_doc_ids=cluster.source_doc_ids,
                        time_range_json=json.dumps(cluster.time_range, ensure_ascii=False),
                        summary_variants_json=json.dumps(
                            [variant.model_dump(mode="json") for variant in cluster.summary_variants],
                            ensure_ascii=False,
                        ),
                        event_time_variants_json=json.dumps(
                            [variant.model_dump(mode="json") for variant in cluster.event_time_variants],
                            ensure_ascii=False,
                        ),
                        conflict_reasons=cluster.conflict_reasons,
                        conflict_status=cluster.conflict_status,
                        primary_entity_id=cluster.primary_entity_id,
                        updated_at=cluster.updated_at.isoformat(),
                    )
                    clusters_created += 1

                    for entity_id in cluster.entity_ids:
                        session.run(
                            """
                            MATCH (e:Entity {id: $entity_id})
                            MATCH (c:EventCluster {id: $cluster_id})
                            MERGE (e)-[r:INVOLVED_IN]->(c)
                            SET r.member_ku_ids = $member_ku_ids,
                                r.source_doc_ids = $source_doc_ids,
                                r.updated_at = $updated_at
                            """,
                            entity_id=entity_id,
                            cluster_id=cluster.cluster_id,
                            member_ku_ids=cluster.member_ku_ids,
                            source_doc_ids=cluster.source_doc_ids,
                            updated_at=cluster.updated_at.isoformat(),
                        )
                        edges_created += 1
        except Exception as exc:
            errors.append(str(exc))

        return {
            "entities_created": entities_created,
            "clusters_created": clusters_created,
            "edges_created": edges_created,
            "errors": errors,
        }
