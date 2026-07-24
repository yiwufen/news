"""
Sync Entity and EventCluster views into Neo4j.
"""

from __future__ import annotations

import json
from typing import Any, ContextManager, Protocol, TypedDict

from src.entities import Entity
from src.event_merging import EventCluster
from src.graph.connection import get_connection
from src.knowledge_base import KnowledgeUnit
from src.schemas.enums import (
    derive_edge_nature,
    derive_edge_scope,
    normalize_relation_type,
)


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
    direct_edges_created: int
    direct_edges_merged: int
    errors: list[str]


class GraphPruneStats(TypedDict):
    orphan_count: int
    edges_migrated: int
    edges_merged: int
    nodes_deleted: int
    errors: list[str]


class KnowledgeGraphSync:
    """Sync Entity / EventCluster / INVOLVED_IN into Neo4j."""

    def __init__(self, connection: GraphConnectionLike | None = None):
        self.connection = connection or get_connection()

    def sync(
        self,
        entities: list[Entity],
        clusters: list[EventCluster],
        *,
        units: list[KnowledgeUnit] | None = None,
    ) -> GraphSyncStats:
        entities_created = 0
        clusters_created = 0
        edges_created = 0
        direct_edges_created = 0
        direct_edges_merged = 0
        errors: list[str] = []

        # Index entities by id so the INVOLVED_IN edge loop can look up each
        # participant's entity_type (for scope derivation). IDs not in this
        # index (e.g. admin path passing a partial entity list) fall back to
        # environment scope via derive_edge_scope(None).
        ent_by_id = {e.entity_id: e for e in entities}

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
                        # Derive edge attributes for multi-hop pruning.
                        # role: the cluster's primary entity is the subject
                        # (actor), other participants are objects. primary_entity_id
                        # comes from event_merging (representative KU's first entity).
                        role = "subject" if entity_id == cluster.primary_entity_id else "object"
                        ent = ent_by_id.get(entity_id)
                        scope = derive_edge_scope(ent.entity_type if ent else None)
                        nature = derive_edge_nature(cluster.cluster_type)
                        session.run(
                            """
                            MATCH (e:Entity {id: $entity_id})
                            MATCH (c:EventCluster {id: $cluster_id})
                            MERGE (e)-[r:INVOLVED_IN]->(c)
                            SET r.member_ku_ids = $member_ku_ids,
                                r.source_doc_ids = $source_doc_ids,
                                r.updated_at = $updated_at,
                                r.role = $role,
                                r.scope = $scope,
                                r.nature = $nature
                            """,
                            entity_id=entity_id,
                            cluster_id=cluster.cluster_id,
                            member_ku_ids=cluster.member_ku_ids,
                            source_doc_ids=cluster.source_doc_ids,
                            updated_at=cluster.updated_at.isoformat(),
                            role=role,
                            scope=scope,
                            nature=nature,
                        )
                        edges_created += 1

                # --- Direct edges (Entity → Entity) from relation_hints ---
                # Only written when units are available (pipeline path). The
                # admin path passes units=None and skips this entirely.
                if units:
                    direct_edges_created, direct_edges_merged = (
                        self._sync_direct_edges(session, units)
                    )
        except Exception as exc:
            errors.append(str(exc))

        return {
            "entities_created": entities_created,
            "clusters_created": clusters_created,
            "edges_created": edges_created,
            "direct_edges_created": direct_edges_created,
            "direct_edges_merged": direct_edges_merged,
            "errors": errors,
        }

    @staticmethod
    def _sync_direct_edges(
        session: Any, units: list[KnowledgeUnit]
    ) -> tuple[int, int]:
        """Write Entity→Entity direct edges from KU relation_hints.

        Returns (created, merged). Each relation_hint whose relation_type maps
        to a stable direct-edge type (OWNERSHIP/GOVERNANCE/COMMERCIAL/RISK)
        becomes a direct edge. One-off events (袭击/签署/…) return (None, None)
        from normalize_relation_type and are skipped — they stay in EventCluster.

        Merge semantics: the same (A, B, type, subtype) seen multiple times
        collapses into one edge. last_seen takes the newest, source_ku_ids the
        union, confidence the max — so repeated observations strengthen rather
        than duplicate the edge.
        """
        # Aggregate hints by (subject, object, type, subtype) so we write each
        # direct edge once with merged properties.
        agg: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for unit in units:
            for hint in unit.relation_hints:
                s_id = hint.subject_entity_id
                o_id = hint.object_entity_id
                if not s_id or not o_id:
                    continue  # unresolved mention — skip
                mapped = normalize_relation_type(hint.relation_type)
                edge_type, subtype = mapped
                if edge_type is None or subtype is None:
                    continue  # one-off event, not a stable relation
                key = (s_id, o_id, edge_type, subtype)
                bucket = agg.setdefault(
                    key,
                    {
                        "source_ku_ids": [],
                        "confidence": 0.0,
                        "last_seen": None,
                    },
                )
                if unit.ku_id not in bucket["source_ku_ids"]:
                    bucket["source_ku_ids"].append(unit.ku_id)
                bucket["confidence"] = max(bucket["confidence"], hint.confidence)
                event_time = unit.time.event_time or unit.time.published_at
                if bucket["last_seen"] is None or event_time > bucket["last_seen"]:
                    bucket["last_seen"] = event_time

        created = 0
        merged = 0
        for (s_id, o_id, edge_type, subtype), props in agg.items():
            last_seen_iso = (
                props["last_seen"].isoformat() if props["last_seen"] else None
            )
            # MERGE on (a, b, type, subtype). ON CREATE seeds first_seen;
            # always update last_seen/source_ku_ids/confidence (merge semantics).
            # source_ku_ids uses coalesce + a parameter list — without APOC we
            # accept potential duplicates in the list (cheap to dedupe later).
            result = session.run(
                f"""
                MATCH (a:Entity {{id: $a_id}}), (b:Entity {{id: $b_id}})
                MERGE (a)-[r:{edge_type} {{subtype: $subtype}}]->(b)
                ON CREATE SET r.first_seen = $last_seen
                SET r.last_seen = $last_seen,
                    r.source_ku_ids = coalesce(r.source_ku_ids, []) + $new_ku_ids,
                    r.confidence = $confidence
                RETURN r.first_seen AS first_seen
                """,
                a_id=s_id,
                b_id=o_id,
                subtype=subtype,
                last_seen=last_seen_iso,
                new_ku_ids=props["source_ku_ids"],
                confidence=props["confidence"],
            )
            # The fake session returns None; the real driver returns a Result.
            # Use presence of first_seen to distinguish create vs merge when the
            # driver is real (best-effort accounting — not critical for correctness).
            try:
                records = result.data() if hasattr(result, "data") else []  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 — fake session / read error
                records = []
            if records and records[0].get("first_seen") == last_seen_iso:
                created += 1
            else:
                merged += 1
        return created, merged

    def prune_orphans(
        self,
        live_entity_ids: list[str],
        name_to_live_id: dict[str, str] | None = None,
    ) -> GraphPruneStats:
        """Delete Neo4j Entity nodes whose id is no longer in SQLite.

        SQLite-side entity merges (``dedup_entities.py`` /
        ``merge_alias_entities.py``) delete duplicate rows but the old
        ``entity_id`` keeps living as an orphan node in Neo4j, still wired
        to EventClusters via INVOLVED_IN edges. Those edges then pollute
        GraphRAG retrieval. This method reconciles the graph against
        ``live_entity_ids`` (the SQLite source of truth):

        For each orphan ``o`` (in graph, not in live_entity_ids):
          1. If a live entity ``l`` with the SAME ``name`` exists:
             - if ``l`` is already a node in the graph: migrate ``o``'s
               INVOLVED_IN edges onto ``l``. When ``l`` already has an edge
               to the same EventCluster, union ``member_ku_ids`` /
               ``source_doc_ids`` so evidence is not lost; otherwise create
               the edge carrying ``o``'s properties. Then delete ``o``.
             - if ``l`` is not yet a node in the graph: re-stamp ``o.id``
               to ``l.id`` (node + inherited edges survive, next ``sync``
               will refresh its properties).
          2. Otherwise (truly deleted, no same-name live entity):
             ``DETACH DELETE`` the node and its edges.

        ``name_to_live_id`` maps ``canonical_name -> live entity_id`` (built
        once from SQLite by the caller). It is required to resolve case 1
        when the live entity has not yet been synced as a node; when omitted,
        those orphans fall back to DETACH DELETE (their edges are dropped,
        the next ``sync`` rebuilds them from the live entity's KUs).

        Pure Cypher, no APOC dependency. All work runs in one session;
        errors are collected per-step rather than aborting the whole prune.
        """
        errors: list[str] = []
        orphan_count = 0
        edges_migrated = 0
        edges_merged = 0
        nodes_deleted = 0

        if not live_entity_ids:
            # Defensive: refusing to prune with an empty live set prevents
            # wiping the graph when a caller hands in a stale/empty id list.
            return {
                "orphan_count": 0,
                "edges_migrated": 0,
                "edges_merged": 0,
                "nodes_deleted": 0,
                "errors": ["prune_orphans refused: live_entity_ids is empty"],
            }

        try:
            with self.connection.session() as session:
                # The real neo4j driver returns a Result with .data(); the
                # GraphSessionLike protocol types run() as -> object, so bind
                # an Any-typed alias for the result-reading paths below.
                s: Any = session
                # Discover orphans and whether each has a same-named live
                # counterpart already present as a graph node. We pass the
                # full live id list once; Neo4j uses the Entity.id unique
                # index to evaluate the NOT IN predicate efficiently.
                orphan_rows = s.run(
                    """
                    MATCH (o:Entity)
                    WHERE NOT o.id IN $live_ids
                    OPTIONAL MATCH (live:Entity)
                        WHERE live.name = o.name AND live.id IN $live_ids
                    RETURN o.id AS orphan_id, o.name AS name,
                           live.id AS live_id_in_graph
                    """,
                    live_ids=live_entity_ids,
                ).data()
                orphan_count = len(orphan_rows)

                for row in orphan_rows:
                    orphan_id = row["orphan_id"]
                    name = row["name"]
                    live_id_in_graph = row["live_id_in_graph"]

                    try:
                        # If no same-named live node exists in the graph but
                        # the live id is known (from SQLite), re-stamp the
                        # orphan so it becomes that live node — edges survive
                        # and the next sync refreshes properties.
                        restamped = False
                        if (
                            live_id_in_graph is None
                            and name_to_live_id
                            and name in name_to_live_id
                        ):
                            live_id = name_to_live_id[name]
                            # Guard: the live id must not already be a node
                            # (handled by the live_id_in_graph branch above),
                            # and must differ from the orphan to avoid a no-op.
                            if live_id != orphan_id:
                                session.run(
                                    """
                                    MATCH (o:Entity {id: $orphan_id})
                                    SET o.id = $live_id
                                    """,
                                    orphan_id=orphan_id,
                                    live_id=live_id,
                                )
                                restamped = True

                        if not restamped:
                            migrated, merged = self._migrate_orphan_edges(
                                session, orphan_id, live_id_in_graph
                            )
                            edges_migrated += migrated
                            edges_merged += merged
                            self._delete_orphan_node(session, orphan_id)
                        nodes_deleted += 1
                    except Exception as exc:  # noqa: BLE001 - surface, continue
                        errors.append(
                            f"prune orphan {orphan_id} ({name!r}): {exc}"
                        )
        except Exception as exc:  # noqa: BLE001 - top-level guard
            errors.append(f"prune_orphans aborted: {exc}")

        return {
            "orphan_count": orphan_count,
            "edges_migrated": edges_migrated,
            "edges_merged": edges_merged,
            "nodes_deleted": nodes_deleted,
            "errors": errors,
        }

    @staticmethod
    def _migrate_orphan_edges(
        session: Any,
        orphan_id: str,
        live_id_in_graph: str | None,
    ) -> tuple[int, int]:
        """Migrate the orphan's INVOLVED_IN edges onto its live counterpart.

        Returns (edges_migrated, edges_merged). When no same-named live node
        exists in the graph, there is nothing to migrate — the caller will
        re-stamp or detach-delete the orphan node itself.
        """
        if live_id_in_graph is None:
            return 0, 0

        migrated = 0
        merged = 0

        # For each (orphan)-[:INVOLVED_IN]->(cluster) edge, either union its
        # properties into the live node's existing edge to that cluster, or
        # create a fresh edge carrying the orphan's properties. We pull the
        # orphan edges first because we cannot safely rewrite the edge we are
        # iterating over in the same statement.
        orphan_edges = session.run(
            """
            MATCH (o:Entity {id: $orphan_id})-[r:INVOLVED_IN]->(c:EventCluster)
            RETURN c.id AS cluster_id,
                   r.member_ku_ids AS member_ku_ids,
                   r.source_doc_ids AS source_doc_ids
            """,
            orphan_id=orphan_id,
        ).data()

        for edge in orphan_edges:
            cluster_id = edge["cluster_id"]
            orph_ku = edge.get("member_ku_ids") or []
            orph_docs = edge.get("source_doc_ids") or []

            existing = session.run(
                """
                MATCH (live:Entity {id: $live_id})-[r:INVOLVED_IN]->(c:EventCluster {id: $cluster_id})
                RETURN r.member_ku_ids AS member_ku_ids,
                       r.source_doc_ids AS source_doc_ids
                """,
                live_id=live_id_in_graph,
                cluster_id=cluster_id,
            ).data()

            if existing:
                # Union properties onto the live edge (evidence-preserving).
                live_row = existing[0]
                live_ku = live_row.get("member_ku_ids") or []
                live_docs = live_row.get("source_doc_ids") or []
                union_ku = list(dict.fromkeys([*live_ku, *orph_ku]))
                union_docs = list(dict.fromkeys([*live_docs, *orph_docs]))
                session.run(
                    """
                    MATCH (live:Entity {id: $live_id})-[r:INVOLVED_IN]->(c:EventCluster {id: $cluster_id})
                    SET r.member_ku_ids = $member_ku_ids,
                        r.source_doc_ids = $source_doc_ids
                    """,
                    live_id=live_id_in_graph,
                    cluster_id=cluster_id,
                    member_ku_ids=union_ku,
                    source_doc_ids=union_docs,
                )
                merged += 1
            else:
                # Create a fresh edge on the live node carrying orphan props.
                session.run(
                    """
                    MATCH (live:Entity {id: $live_id}), (c:EventCluster {id: $cluster_id})
                    MERGE (live)-[r:INVOLVED_IN]->(c)
                    SET r.member_ku_ids = $member_ku_ids,
                        r.source_doc_ids = $source_doc_ids
                    """,
                    live_id=live_id_in_graph,
                    cluster_id=cluster_id,
                    member_ku_ids=orph_ku,
                    source_doc_ids=orph_docs,
                )
                migrated += 1

        return migrated, merged

    @staticmethod
    def _delete_orphan_node(session: Any, orphan_id: str) -> None:
        """Delete the orphan node and any edges still attached to it."""
        session.run(
            "MATCH (o:Entity {id: $orphan_id}) DETACH DELETE o",
            orphan_id=orphan_id,
        )

    def delete_node(self, node_id: str) -> bool:
        """Delete any node (Entity or EventCluster) by id, detaching its edges.

        Used by the admin write path (entity/cluster merge/split/delete) to keep
        Neo4j in sync when SQLite-side rows are removed. Returns True if a node
        was deleted.
        """
        with self.connection.session() as session:
            result = session.run(
                "MATCH (n {id: $node_id}) DETACH DELETE n "
                "RETURN count(n) AS deleted",
                node_id=node_id,
            )
            rows = result.data() if hasattr(result, "data") else []  # type: ignore[union-attr]
            return bool(rows and rows[0].get("deleted", 0) > 0)
