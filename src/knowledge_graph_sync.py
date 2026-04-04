"""
Entity + EventCluster 鍥捐氨鍚屾銆?"""

from __future__ import annotations

from typing import ContextManager, Protocol, TypedDict

from src.entities_v2 import Entity
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
    """鍚屾 Entity / EventCluster / INVOLVED_IN 鍥捐氨銆?"""

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
                            e.identifiers = $identifiers,
                            e.tags = $tags,
                            e.source_ku_ids = $source_ku_ids,
                            e.updated_at = $updated_at
                        """,
                        id=entity.entity_id,
                        name=entity.canonical_name,
                        entity_type=entity.entity_type,
                        aliases=entity.aliases,
                        identifiers=entity.identifiers,
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
                            c.member_ku_ids = $member_ku_ids,
                            c.source_doc_ids = $source_doc_ids,
                            c.conflict_status = $conflict_status,
                            c.updated_at = $updated_at
                        """,
                        id=cluster.cluster_id,
                        cluster_type=cluster.cluster_type,
                        title=cluster.title,
                        summary=cluster.summary,
                        member_ku_ids=cluster.member_ku_ids,
                        source_doc_ids=cluster.source_doc_ids,
                        conflict_status=cluster.conflict_status,
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
