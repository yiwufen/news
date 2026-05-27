"""Admin 写入操作 Service 层 — 统一编排 snapshot → mutate → log → sync。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.admin.audit import AuditLogRepository
from src.admin.auth import TokenPayload
from src.entities import Entity
from src.event_merging import EventCluster

if TYPE_CHECKING:
    from src.graph.nodes import NodeRepository
    from src.knowledge_graph_sync import KnowledgeGraphSync

logger = logging.getLogger(__name__)


class AdminWriteService:
    """所有写入 Router 调用此 Service，保证操作可审计、可撤销。"""

    def __init__(self, db_path: str, user: TokenPayload):
        self.db_path = db_path
        self.user = user

        # 延迟导入避免循环依赖
        from src.entities import EntityRepository
        from src.event_merging import EventClusterRepository
        from src.knowledge_base import (
            KnowledgeProcessingLogRepository,
            KnowledgeUnitRepository,
            RawDocumentRepository,
        )

        self.entity_repo = EntityRepository(db_path)
        self.cluster_repo = EventClusterRepository(db_path)
        self.ku_repo = KnowledgeUnitRepository(db_path)
        self.log_repo = KnowledgeProcessingLogRepository(db_path)
        self.raw_doc_repo = RawDocumentRepository(db_path)
        self.audit_repo = AuditLogRepository(db_path)

    # -- 懒加载 Neo4j 连接（可能不可用） --

    _graph_sync: KnowledgeGraphSync | None = None
    _node_repo: NodeRepository | None = None
    _graph_attempted: bool = False

    def _ensure_graph(self) -> None:
        if self._graph_attempted:
            return
        self._graph_attempted = True
        try:
            from src.graph.connection import get_connection
            from src.graph.nodes import NodeRepository
            from src.knowledge_graph_sync import KnowledgeGraphSync
            conn = get_connection()
            self._graph_sync = KnowledgeGraphSync(conn)
            self._node_repo = NodeRepository(conn)
        except Exception:
            logger.debug("Neo4j not available, graph sync disabled")

    @property
    def graph_sync(self) -> KnowledgeGraphSync | None:
        self._ensure_graph()
        return self._graph_sync

    @property
    def node_repo(self) -> NodeRepository | None:
        self._ensure_graph()
        return self._node_repo

    def _sync_graph(self, entities=None, clusters=None) -> None:
        """Best-effort Neo4j 同步，失败不影响主流程。"""
        gs = self.graph_sync
        if gs is None:
            return
        try:
            gs.sync(entities or [], clusters or [])
        except Exception:
            logger.warning("Neo4j sync failed, SQLite is authoritative", exc_info=True)

    def _delete_graph_node(self, node_id: str) -> None:
        nr = self.node_repo
        if nr is None:
            return
        try:
            nr.delete_node(node_id)
        except Exception:
            logger.warning("Neo4j delete failed for %s", node_id, exc_info=True)

    def _audit(self, action: str, resource_type: str, resource_id: str, **kwargs) -> int:
        return self.audit_repo.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=self.user.user_id,
            username=self.user.username,
            **kwargs,
        )

    # -- Phase 2B: 实体操作 --

    def _find_cluster_ids_by_entity(self, entity_id: str) -> list[str]:
        """通过 cluster_entity_map 查找引用指定 entity_id 的集群 IDs。"""
        with self.cluster_repo._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                "SELECT DISTINCT cluster_id FROM cluster_entity_map WHERE entity_id = ?",
                (entity_id,),
            ).fetchall()
        return [r["cluster_id"] for r in rows]

    def _update_kus_entity_refs(self, old_entity_id: str, new_entity_id: str) -> list[str]:
        """将 KU 中的 entity_ref.entity_id 从 old 替换为 new，返回被修改的 ku_ids。"""
        ku_ids = self.ku_repo.find_by_entity_ids([old_entity_id])
        if not ku_ids:
            return []
        kus = self.ku_repo.get_by_ids(ku_ids)
        for ku in kus:
            for ref in ku.entities:
                if ref.entity_id == old_entity_id:
                    ref.entity_id = new_entity_id
        self.ku_repo.save_batch(kus)
        return [ku.ku_id for ku in kus]

    def _update_clusters_entity_refs(
        self, old_entity_id: str, new_entity_id: str | None
    ) -> list[str]:
        """更新集群中 entity_ids 列表的引用。new_entity_id=None 表示移除。"""
        cluster_ids = self._find_cluster_ids_by_entity(old_entity_id)
        if not cluster_ids:
            return []
        clusters = self.cluster_repo.get_by_ids(cluster_ids)
        updated: list[EventCluster] = []
        for cluster in clusters:
            if old_entity_id not in cluster.entity_ids:
                continue
            if new_entity_id is not None:
                cluster.entity_ids = [
                    new_entity_id if eid == old_entity_id else eid
                    for eid in cluster.entity_ids
                ]
            else:
                cluster.entity_ids = [eid for eid in cluster.entity_ids if eid != old_entity_id]
            cluster.updated_at = datetime.now(UTC)
            updated.append(cluster)
        if updated:
            self.cluster_repo.save_batch(updated)
        return [c.cluster_id for c in updated]

    def entity_edit(self, entity_id: str, updates: dict) -> Entity:
        entities = self.entity_repo.get_by_ids([entity_id])
        if not entities:
            raise ValueError(f"Entity {entity_id} not found")
        entity = entities[0]
        old_state = entity.model_dump(mode="json")

        allowed = {"canonical_name", "entity_type", "description", "aliases", "identifiers", "tags"}
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(entity, key, value)
        entity.updated_at = datetime.now(UTC)

        self.entity_repo.save_batch([entity])
        self._sync_graph(entities=[entity])
        self._audit(
            action="entity.edit",
            resource_type="entity",
            resource_id=entity_id,
            old_state=old_state,
            new_state=entity.model_dump(mode="json"),
        )
        return entity

    def entity_merge(self, source_id: str, target_id: str) -> Entity:
        if source_id == target_id:
            raise ValueError("source_id and target_id must be different")

        source_list = self.entity_repo.get_by_ids([source_id])
        target_list = self.entity_repo.get_by_ids([target_id])
        if not source_list:
            raise ValueError(f"Source entity {source_id} not found")
        if not target_list:
            raise ValueError(f"Target entity {target_id} not found")

        source = source_list[0]
        target = target_list[0]
        old_state = {
            "source": source.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
        }

        # Snapshot KU states BEFORE any mutation (for undo)
        pre_merge_ku_ids = self.ku_repo.find_by_entity_ids([source_id])
        pre_merge_ku_states = [
            ku.model_dump(mode="json")
            for ku in self.ku_repo.get_by_ids(pre_merge_ku_ids)
        ] if pre_merge_ku_ids else []

        # Snapshot affected clusters BEFORE mutation
        pre_merge_cluster_ids = self._find_cluster_ids_by_entity(source_id)

        # Merge into target
        _MAX_ALIASES = 10
        seen_aliases = set()
        merged_aliases: list[str] = []
        for alias in [*target.aliases, source.canonical_name, *source.aliases, target.canonical_name]:
            norm = alias.strip().lower()
            if norm and norm not in seen_aliases:
                seen_aliases.add(norm)
                merged_aliases.append(alias)
        target.aliases = merged_aliases[:_MAX_ALIASES]

        for key, value in source.identifiers.items():
            if key not in target.identifiers:
                target.identifiers[key] = value

        target.source_ku_ids = list(dict.fromkeys([*target.source_ku_ids, *source.source_ku_ids]))
        target.tags = list(dict.fromkeys([*target.tags, *source.tags]))
        if not target.description and source.description:
            target.description = source.description
        target.updated_at = datetime.now(UTC)

        # Persist: save merged target, delete source
        self.entity_repo.save_batch([target])
        self.entity_repo.delete_by_id(source_id)

        # Update KUs
        self._update_kus_entity_refs(source_id, target_id)

        # Update clusters
        updated_cluster_ids = self._update_clusters_entity_refs(source_id, target_id)

        # Neo4j
        self._delete_graph_node(source_id)
        updated_clusters = self.cluster_repo.get_by_ids(updated_cluster_ids) if updated_cluster_ids else []
        self._sync_graph(entities=[target], clusters=updated_clusters)

        # Audit — metadata contains pre-merge snapshots for undo
        self._audit(
            action="entity.merge",
            resource_type="entity",
            resource_id=target_id,
            old_state=old_state,
            new_state=target.model_dump(mode="json"),
            metadata={
                "source_id": source_id,
                "updated_cluster_ids": updated_cluster_ids,
                "pre_merge_ku_states": pre_merge_ku_states,
                "pre_merge_cluster_ids": pre_merge_cluster_ids,
            },
        )
        return target

    def entity_split(
        self, entity_id: str, new_entities_spec: list[dict]
    ) -> list[Entity]:
        source_list = self.entity_repo.get_by_ids([entity_id])
        if not source_list:
            raise ValueError(f"Entity {entity_id} not found")
        source = source_list[0]
        old_state = source.model_dump(mode="json")

        # Validate all assigned KU IDs cover source_ku_ids
        all_assigned: set[str] = set()
        for spec in new_entities_spec:
            all_assigned.update(spec.get("ku_ids", []))
        source_ku_set = set(source.source_ku_ids)
        if all_assigned != source_ku_set:
            missing = source_ku_set - all_assigned
            extra = all_assigned - source_ku_set
            parts = []
            if missing:
                parts.append(f"missing: {missing}")
            if extra:
                parts.append(f"extra: {extra}")
            raise ValueError(f"KU assignment mismatch: {'; '.join(parts)}")

        # Create new entities
        now = datetime.now(UTC)
        new_entities: list[Entity] = []
        for spec in new_entities_spec:
            new_entity = Entity(
                canonical_name=spec["canonical_name"],
                entity_type=spec.get("entity_type") or source.entity_type,
                aliases=spec.get("aliases") or [],
                identifiers={**source.identifiers, **spec.get("identifiers", {})},
                description=spec.get("description") or source.description,
                tags=list(source.tags),
                source_ku_ids=spec.get("ku_ids", []),
                created_at=now,
                updated_at=now,
            )
            new_entities.append(new_entity)

        # Persist
        self.entity_repo.save_batch(new_entities)
        self.entity_repo.delete_by_id(entity_id)

        # Update KUs: reassign entity_id references
        for new_entity in new_entities:
            self._update_kus_entity_refs(entity_id, new_entity.entity_id)

        # Update clusters
        cluster_ids = self._find_cluster_ids_by_entity(entity_id)
        if cluster_ids:
            clusters = self.cluster_repo.get_by_ids(cluster_ids)
            for cluster in clusters:
                if entity_id in cluster.entity_ids:
                    cluster.entity_ids = [
                        eid for eid in cluster.entity_ids if eid != entity_id
                    ]
                    # Add all new entity IDs
                    for ne in new_entities:
                        if ne.entity_id not in cluster.entity_ids:
                            cluster.entity_ids.append(ne.entity_id)
                    cluster.updated_at = now
            self.cluster_repo.save_batch(clusters)

        # Neo4j
        self._delete_graph_node(entity_id)
        self._sync_graph(entities=new_entities)

        self._audit(
            action="entity.split",
            resource_type="entity",
            resource_id=entity_id,
            old_state=old_state,
            new_state=[e.model_dump(mode="json") for e in new_entities],
            metadata={"new_entity_ids": [e.entity_id for e in new_entities]},
        )
        return new_entities

    def entity_delete(self, entity_id: str) -> None:
        source_list = self.entity_repo.get_by_ids([entity_id])
        if not source_list:
            raise ValueError(f"Entity {entity_id} not found")
        source = source_list[0]
        old_state = source.model_dump(mode="json")

        # Snapshot cross-references BEFORE removal (for undo)
        ku_ids = self.ku_repo.find_by_entity_ids([entity_id])
        pre_delete_ku_states = [
            ku.model_dump(mode="json")
            for ku in self.ku_repo.get_by_ids(ku_ids)
        ] if ku_ids else []
        pre_delete_cluster_ids = self._find_cluster_ids_by_entity(entity_id)

        # Remove entity_id from KUs
        if ku_ids:
            kus = self.ku_repo.get_by_ids(ku_ids)
            for ku in kus:
                ku.entities = [ref for ref in ku.entities if ref.entity_id != entity_id]
            self.ku_repo.save_batch(kus)

        # Remove from clusters
        self._update_clusters_entity_refs(entity_id, None)

        # Delete from SQLite + Neo4j
        self.entity_repo.delete_by_id(entity_id)
        self._delete_graph_node(entity_id)

        self._audit(
            action="entity.delete",
            resource_type="entity",
            resource_id=entity_id,
            old_state=old_state,
            metadata={
                "pre_delete_ku_states": pre_delete_ku_states,
                "pre_delete_cluster_ids": pre_delete_cluster_ids,
            },
        )

    # -- Phase 2C: 集群操作 --

    def cluster_edit(self, cluster_id: str, updates: dict) -> EventCluster:
        clusters = self.cluster_repo.get_by_ids([cluster_id])
        if not clusters:
            raise ValueError(f"Cluster {cluster_id} not found")
        cluster = clusters[0]
        old_state = cluster.model_dump(mode="json")

        allowed = {"title", "summary", "primary_entity_id", "conflict_status"}
        overrides = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not overrides:
            raise ValueError("No valid fields to update")

        # Store as manual overrides so _repair_clusters won't overwrite
        cluster.manual_overrides = {**cluster.manual_overrides, **overrides}
        for key, value in overrides.items():
            setattr(cluster, key, value)
        cluster.updated_at = datetime.now(UTC)

        self.cluster_repo.save_batch([cluster])
        self._sync_graph(clusters=[cluster])
        self._audit(
            action="cluster.edit",
            resource_type="cluster",
            resource_id=cluster_id,
            old_state=old_state,
            new_state=cluster.model_dump(mode="json"),
        )
        return cluster

    def cluster_merge(self, cluster_ids: list[str]) -> EventCluster:
        from src.event_merging import build_event_cluster_snapshot

        if len(cluster_ids) < 2:
            raise ValueError("Need at least 2 clusters to merge")

        clusters = self.cluster_repo.get_by_ids(cluster_ids)
        if len(clusters) != len(cluster_ids):
            found = {c.cluster_id for c in clusters}
            missing = set(cluster_ids) - found
            raise ValueError(f"Clusters not found: {missing}")

        old_states = {c.cluster_id: c.model_dump(mode="json") for c in clusters}

        # Collect all member KUs
        all_ku_ids: list[str] = []
        for c in clusters:
            all_ku_ids.extend(c.member_ku_ids)
        all_ku_ids = list(dict.fromkeys(all_ku_ids))

        member_units = self.ku_repo.get_by_ids(all_ku_ids)
        if not member_units:
            raise ValueError("No member KUs found across the clusters")

        new_cluster = build_event_cluster_snapshot(member_units)
        self.cluster_repo.save_batch([new_cluster])

        # Delete old clusters
        for cid in cluster_ids:
            self.cluster_repo.delete_by_id(cid)
            self._delete_graph_node(cid)

        # Update KUs' cluster_id
        for unit in member_units:
            unit.cluster_id = new_cluster.cluster_id
        self.ku_repo.save_batch(member_units)

        self._sync_graph(clusters=[new_cluster])
        self._audit(
            action="cluster.merge",
            resource_type="cluster",
            resource_id=new_cluster.cluster_id,
            old_state=old_states,
            new_state=new_cluster.model_dump(mode="json"),
            metadata={"merged_cluster_ids": cluster_ids},
        )
        return new_cluster

    def cluster_split(self, cluster_id: str, remove_ku_ids: list[str]) -> EventCluster:
        from src.event_merging import build_event_cluster_snapshot

        clusters = self.cluster_repo.get_by_ids([cluster_id])
        if not clusters:
            raise ValueError(f"Cluster {cluster_id} not found")
        cluster = clusters[0]
        old_state = cluster.model_dump(mode="json")

        remove_set = set(remove_ku_ids)
        remaining_ku_ids = [k for k in cluster.member_ku_ids if k not in remove_set]
        if not remaining_ku_ids:
            raise ValueError("Cannot remove all members from cluster; use delete instead")
        if len(remaining_ku_ids) == len(cluster.member_ku_ids):
            raise ValueError("None of the specified KU IDs are members of this cluster")

        remaining_units = self.ku_repo.get_by_ids(remaining_ku_ids)
        rebuilt = build_event_cluster_snapshot(remaining_units, cluster_id=cluster_id)
        # Preserve manual overrides
        rebuilt.manual_overrides = cluster.manual_overrides
        self.cluster_repo.save_batch([rebuilt])

        # Detach removed KUs
        removed_units = self.ku_repo.get_by_ids(list(remove_set))
        for unit in removed_units:
            unit.cluster_id = None
        self.ku_repo.save_batch(removed_units)

        self._sync_graph(clusters=[rebuilt])
        self._audit(
            action="cluster.split",
            resource_type="cluster",
            resource_id=cluster_id,
            old_state=old_state,
            new_state=rebuilt.model_dump(mode="json"),
            metadata={"removed_ku_ids": list(remove_set)},
        )
        return rebuilt

    def cluster_delete(self, cluster_id: str) -> None:
        clusters = self.cluster_repo.get_by_ids([cluster_id])
        if not clusters:
            raise ValueError(f"Cluster {cluster_id} not found")
        cluster = clusters[0]
        old_state = cluster.model_dump(mode="json")

        # Detach member KUs
        if cluster.member_ku_ids:
            kus = self.ku_repo.get_by_ids(cluster.member_ku_ids)
            for ku in kus:
                ku.cluster_id = None
            self.ku_repo.save_batch(kus)

        self.cluster_repo.delete_by_id(cluster_id)
        self._delete_graph_node(cluster_id)

        self._audit(
            action="cluster.delete",
            resource_type="cluster",
            resource_id=cluster_id,
            old_state=old_state,
            metadata={"member_ku_ids": cluster.member_ku_ids},
        )

    # -- Phase 2D: 文档重新处理 --

    def _get_pipeline(self):
        """懒加载 ContinuousPipeline 实例（需要 LLM 配置，可能失败）。"""
        if not hasattr(self, "_pipeline"):
            from src.pipeline.continuous import ContinuousPipeline
            self._pipeline = ContinuousPipeline(
                db_path=self.db_path,
                graph_enabled=self.graph_sync is not None,
            )
        return self._pipeline

    def reprocess_document(self, doc_id: str) -> dict:
        """重新处理单个文档。"""
        pipeline = self._get_pipeline()
        result = pipeline.process_single_document(doc_id)

        self._audit(
            action="doc.reprocess",
            resource_type="document",
            resource_id=doc_id,
            old_state=None,
            new_state={
                "status": result.status,
                "knowledge_units_count": result.knowledge_units_count,
                "entities_count": result.entities_count,
                "clusters_count": result.clusters_count,
                "error_message": result.error_message,
            },
        )
        return {
            "doc_id": result.doc_id,
            "status": result.status,
            "knowledge_units_count": result.knowledge_units_count,
            "entities_count": result.entities_count,
            "clusters_count": result.clusters_count,
            "error_message": result.error_message,
        }

    def reprocess_batch(self, doc_ids: list[str]) -> list[dict]:
        """批量重新处理文档（上限 50）。"""
        if len(doc_ids) > 50:
            raise ValueError("Batch size exceeds maximum of 50")
        return [self.reprocess_document(doc_id) for doc_id in doc_ids]

    # -- Phase 2E: 撤销 --

    def undo(self, log_id: int) -> dict:
        """撤销指定审计条目记录的操作。"""
        entry = self.audit_repo.get_by_id(log_id)
        if entry is None:
            raise ValueError(f"Audit log entry {log_id} not found")
        if not entry.get("old_state"):
            raise ValueError(f"Audit log entry {log_id} has no old_state to restore")

        action: str = entry["action"]
        resource_type: str = entry["resource_type"]
        resource_id: str = entry["resource_id"]
        old_state: dict = entry["old_state"]

        if action.startswith("undo."):
            raise ValueError("Cannot undo an undo operation")

        if resource_type == "entity":
            return self._undo_entity(action, resource_id, old_state, entry)
        elif resource_type == "cluster":
            return self._undo_cluster(action, resource_id, old_state, entry)
        elif resource_type == "document":
            raise ValueError("Document reprocessing cannot be undone")
        else:
            raise ValueError(f"Undo not supported for resource_type={resource_type}")

    def _undo_entity(self, action: str, resource_id: str, old_state: dict, entry: dict) -> dict:
        metadata = entry.get("metadata") or {}

        if action == "entity.edit":
            entity = Entity.model_validate(old_state)
            self.entity_repo.save_batch([entity])
            self._sync_graph(entities=[entity])
            self._audit(
                action=f"undo.{action}",
                resource_type="entity",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid {action} for entity {resource_id}", "restored": resource_id}

        if action == "entity.delete":
            entity = Entity.model_validate(old_state)
            self.entity_repo.save_batch([entity])

            # Restore KU cross-references
            pre_delete_ku_states = metadata.get("pre_delete_ku_states", [])
            if pre_delete_ku_states:
                from src.knowledge_base import KnowledgeUnit
                restored_kus = [KnowledgeUnit.model_validate(d) for d in pre_delete_ku_states]
                self.ku_repo.save_batch(restored_kus)

            # Restore cluster entity_ids
            pre_delete_cluster_ids = metadata.get("pre_delete_cluster_ids", [])
            if pre_delete_cluster_ids:
                clusters = self.cluster_repo.get_by_ids(pre_delete_cluster_ids)
                for cluster in clusters:
                    if resource_id not in cluster.entity_ids:
                        cluster.entity_ids.append(resource_id)
                        cluster.updated_at = datetime.now(UTC)
                if clusters:
                    self.cluster_repo.save_batch(clusters)

            self._sync_graph(entities=[entity])
            self._audit(
                action=f"undo.{action}",
                resource_type="entity",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid {action} for entity {resource_id}", "restored": resource_id}

        if action == "entity.merge":
            if not isinstance(old_state, dict) or "source" not in old_state or "target" not in old_state:
                raise ValueError("Undo entity.merge requires source+target in old_state")

            source_entity = Entity.model_validate(old_state["source"])
            target_entity = Entity.model_validate(old_state["target"])
            self.entity_repo.save_batch([source_entity, target_entity])

            # Restore pre-merge KU states
            pre_merge_ku_states = metadata.get("pre_merge_ku_states", [])
            if pre_merge_ku_states:
                from src.knowledge_base import KnowledgeUnit
                restored_kus = [KnowledgeUnit.model_validate(d) for d in pre_merge_ku_states]
                self.ku_repo.save_batch(restored_kus)

            # Restore cluster entity_ids (re-add source_id to clusters that had it)
            pre_merge_cluster_ids = metadata.get("pre_merge_cluster_ids", [])
            if pre_merge_cluster_ids:
                clusters = self.cluster_repo.get_by_ids(pre_merge_cluster_ids)
                for cluster in clusters:
                    # Replace target_id back to source_id where appropriate
                    if target_entity.entity_id in cluster.entity_ids and source_entity.entity_id not in cluster.entity_ids:
                        cluster.entity_ids = [
                            source_entity.entity_id if eid == target_entity.entity_id else eid
                            for eid in cluster.entity_ids
                        ]
                        cluster.updated_at = datetime.now(UTC)
                if clusters:
                    self.cluster_repo.save_batch(clusters)

            self._sync_graph(entities=[source_entity, target_entity])
            self._audit(
                action="undo.entity.merge",
                resource_type="entity",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state={"source": source_entity.model_dump(mode="json"), "target": target_entity.model_dump(mode="json")},
            )
            return {
                "message": f"Undid entity.merge: restored {source_entity.entity_id} and {target_entity.entity_id}",
                "restored": [source_entity.entity_id, target_entity.entity_id],
            }

        if action == "entity.split":
            metadata = entry.get("metadata") or {}
            new_entity_ids = metadata.get("new_entity_ids", [])

            # Restore source entity from old_state
            source_entity = Entity.model_validate(old_state)
            self.entity_repo.save_batch([source_entity])

            # Delete the split-off entities
            for eid in new_entity_ids:
                self.entity_repo.delete_by_id(eid)
                self._delete_graph_node(eid)

            # Restore KU entity_id references
            for eid in new_entity_ids:
                self._update_kus_entity_refs(eid, source_entity.entity_id)

            self._sync_graph(entities=[source_entity])
            self._audit(
                action="undo.entity.split",
                resource_type="entity",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid entity.split: restored {resource_id}", "restored": resource_id}

        raise ValueError(f"Undo not supported for entity action={action}")

    def _undo_cluster(self, action: str, resource_id: str, old_state: dict, entry: dict) -> dict:
        from src.event_merging import EventCluster

        metadata = entry.get("metadata") or {}

        if action == "cluster.edit":
            cluster = EventCluster.model_validate(old_state)
            self.cluster_repo.save_batch([cluster])
            self._sync_graph(clusters=[cluster])
            self._audit(
                action=f"undo.{action}",
                resource_type="cluster",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid {action} for cluster {resource_id}", "restored": resource_id}

        if action == "cluster.delete":
            cluster = EventCluster.model_validate(old_state)
            self.cluster_repo.save_batch([cluster])

            # Re-attach member KUs
            member_ku_ids = metadata.get("member_ku_ids", [])
            if member_ku_ids:
                kus = self.ku_repo.get_by_ids(member_ku_ids)
                for ku in kus:
                    ku.cluster_id = cluster.cluster_id
                self.ku_repo.save_batch(kus)

            self._sync_graph(clusters=[cluster])
            self._audit(
                action=f"undo.{action}",
                resource_type="cluster",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid {action} for cluster {resource_id}", "restored": resource_id}

        if action == "cluster.merge":
            metadata = entry.get("metadata") or {}
            merged_cluster_ids = metadata.get("merged_cluster_ids", [])

            # old_state is a dict of {cluster_id: cluster_json, ...}
            if not isinstance(old_state, dict):
                raise ValueError("Undo cluster.merge requires old_state as dict of cluster snapshots")

            # Delete the merged cluster
            self.cluster_repo.delete_by_id(resource_id)
            self._delete_graph_node(resource_id)

            # Restore old clusters
            restored: list[EventCluster] = []
            for cid, cluster_json in old_state.items():
                cluster = EventCluster.model_validate(cluster_json)
                self.cluster_repo.save_batch([cluster])
                restored.append(cluster)

                # Restore KU cluster_id references
                for ku_id in cluster.member_ku_ids:
                    kus = self.ku_repo.get_by_ids([ku_id])
                    if kus:
                        kus[0].cluster_id = cluster.cluster_id
                        self.ku_repo.save_batch(kus)

            self._sync_graph(clusters=restored)
            self._audit(
                action="undo.cluster.merge",
                resource_type="cluster",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {
                "message": f"Undid cluster.merge: restored {len(restored)} clusters",
                "restored": [c.cluster_id for c in restored],
            }

        if action == "cluster.split":
            metadata = entry.get("metadata") or {}
            removed_ku_ids = metadata.get("removed_ku_ids", [])

            # Restore original cluster from old_state
            cluster = EventCluster.model_validate(old_state)
            self.cluster_repo.save_batch([cluster])

            # Re-attach removed KUs
            if removed_ku_ids:
                kus = self.ku_repo.get_by_ids(removed_ku_ids)
                for ku in kus:
                    ku.cluster_id = cluster.cluster_id
                self.ku_repo.save_batch(kus)

            self._sync_graph(clusters=[cluster])
            self._audit(
                action="undo.cluster.split",
                resource_type="cluster",
                resource_id=resource_id,
                old_state=entry.get("new_state"),
                new_state=old_state,
            )
            return {"message": f"Undid cluster.split for {resource_id}", "restored": resource_id}

        raise ValueError(f"Undo not supported for cluster action={action}")
