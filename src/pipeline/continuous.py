"""
持续运行模式入口。

完整的持续运行流程：
原始文档 -> KnowledgeUnit -> Entity/EventCluster -> 图谱同步 -> legacy 回填
"""

from __future__ import annotations

from dataclasses import dataclass

from collectors.database import Database
from src.entities_v2 import EntityResolver, EntityRepository
from src.event_clustering import EventClusterRepository, EventClusterer
from src.knowledge_base import (
    KnowledgeProcessingLogRepository,
    KnowledgeToLegacyParticleAdapter,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocumentRepository,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.schemas import IntelligenceParticle


@dataclass
class ContinuousRunResult:
    """持续运行结果"""

    particles_extracted: int
    particles_saved: int
    nodes_created: int
    edges_created: int
    errors: list[str]
    particles: list[IntelligenceParticle]
    knowledge_units_extracted: int = 0
    knowledge_units_saved: int = 0
    entities_saved: int = 0
    clusters_saved: int = 0


class ContinuousPipeline:
    """持续运行模式流水线

    完整流程：
    1. 从数据库读取未处理的新闻
    2. Worker Agent 提取情报微粒
    3. 保存到 SQLite
    4. Integrator Agent 实体对齐 + 图谱同步

    这是持续运行模式的标准入口，产出：
    - SQLite: 情报微粒存储
    - Neo4j: 知识图谱
    """

    def __init__(
        self,
        batch_size: int = 10,
        graph_enabled: bool = True,
        incremental: bool = True,
        db_path: str = "data/news.db",
        extractor: KnowledgeExtractor | None = None,
    ):
        """初始化持续运行流水线

        Args:
            batch_size: 每批处理数量
            graph_enabled: 是否启用图谱同步（默认启用）
            incremental: 是否增量处理
        """
        self.batch_size = batch_size
        self.graph_enabled = graph_enabled
        self.incremental = incremental
        self.db = Database(db_path)
        self.raw_documents = RawDocumentRepository(db_path)
        self.knowledge_units = KnowledgeUnitRepository(db_path)
        self.entity_repo = EntityRepository(db_path)
        self.cluster_repo = EventClusterRepository(db_path)
        self.log_repo = KnowledgeProcessingLogRepository(db_path)
        self.extractor = extractor or KnowledgeExtractor()
        self.entity_resolver = EntityResolver(self.entity_repo)
        self.clusterer = EventClusterer(self.cluster_repo)
        self.graph_sync = KnowledgeGraphSync() if graph_enabled else None
        self.legacy_adapter = KnowledgeToLegacyParticleAdapter()

    def run(
        self,
        time_window: str | None = None,
        dry_run: bool = False,
    ) -> ContinuousRunResult:
        """运行持续处理流程

        Args:
            time_window: 时间切片过滤 (YYYY-WNN)
            dry_run: 仅测试，不保存

        Returns:
            ContinuousRunResult: 处理结果
        """
        errors: list[str] = []
        all_particles: list[IntelligenceParticle] = []
        all_units: list[KnowledgeUnit] = []
        total_nodes = 0
        total_edges = 0
        total_entities_saved = 0
        total_clusters_saved = 0

        for batch in self.raw_documents.iter_documents(
            batch_size=self.batch_size,
            time_window=time_window,
            incremental=self.incremental,
        ):
            batch_units: list[KnowledgeUnit] = []
            batch_log_records: list[dict[str, object]] = []
            extracted_by_doc: dict[str, list[KnowledgeUnit]] = {}

            for document in batch:
                try:
                    units = self.extractor.extract(document)
                    extracted_by_doc[document.doc_id] = units
                    batch_units.extend(units)
                    all_units.extend(units)
                except Exception as exc:
                    errors.append(f"[{document.doc_id}] KnowledgeUnit 提取失败: {exc}")
                    batch_log_records.append(
                        {
                            "doc_id": document.doc_id,
                            "status": "failed",
                            "error_message": str(exc),
                        }
                    )

            if not batch_units:
                if not dry_run and batch_log_records:
                    self.log_repo.log_batch(batch_log_records)
                continue

            resolved_units, resolved_entities = self.entity_resolver.resolve_units(
                batch_units,
                persist=not dry_run,
            )
            clustered_units, clusters = self.clusterer.assign_clusters(
                resolved_units,
                persist=not dry_run,
            )
            legacy_particles: list[IntelligenceParticle] = []
            legacy_rows: list[dict[str, object]] = []
            for unit in clustered_units:
                legacy_particle = self.legacy_adapter.to_legacy_particle(unit)
                legacy_row = self.legacy_adapter.to_legacy_row(unit)
                if legacy_particle is None or legacy_row is None:
                    continue
                legacy_particles.append(legacy_particle)
                legacy_rows.append(legacy_row)
            all_particles.extend(legacy_particles)

            graph_sync_error_message: str | None = None
            if not dry_run:
                self.knowledge_units.save_batch(clustered_units)
                if legacy_rows:
                    self.db.insert_particles_batch(legacy_rows)

                if self.graph_enabled and self.graph_sync:
                    sync_result = self.graph_sync.sync(resolved_entities, clusters)
                    total_nodes += sync_result["entities_created"] + sync_result["clusters_created"]
                    total_edges += sync_result["edges_created"]
                    errors.extend(sync_result["errors"])
                    if sync_result["errors"]:
                        graph_sync_error_message = "; ".join(sync_result["errors"])

            total_entities_saved += len(resolved_entities)
            total_clusters_saved += len(clusters)

            entities_by_doc: dict[str, set[str]] = {doc.doc_id: set() for doc in batch}
            clusters_by_doc: dict[str, set[str]] = {doc.doc_id: set() for doc in batch}
            for unit in clustered_units:
                entities_by_doc.setdefault(unit.source.doc_id, set()).update(
                    entity.entity_id for entity in unit.entities if entity.entity_id
                )
                if unit.cluster_id:
                    clusters_by_doc.setdefault(unit.source.doc_id, set()).add(unit.cluster_id)

            for document in batch:
                if any(record["doc_id"] == document.doc_id for record in batch_log_records):
                    continue
                doc_units = extracted_by_doc.get(document.doc_id, [])
                status = "failed" if graph_sync_error_message else "success"
                batch_log_records.append(
                    {
                        "doc_id": document.doc_id,
                        "status": status,
                        "knowledge_units_count": len(doc_units),
                        "entities_count": len(entities_by_doc.get(document.doc_id, set())),
                        "clusters_count": len(clusters_by_doc.get(document.doc_id, set())),
                        "error_message": graph_sync_error_message,
                    }
                )

            if not dry_run:
                self.log_repo.log_batch(batch_log_records)

        return ContinuousRunResult(
            particles_extracted=len(all_particles),
            particles_saved=len(all_particles) if not dry_run else 0,
            nodes_created=total_nodes,
            edges_created=total_edges,
            errors=errors,
            particles=all_particles,
            knowledge_units_extracted=len(all_units),
            knowledge_units_saved=len(all_units) if not dry_run else 0,
            entities_saved=total_entities_saved if not dry_run else 0,
            clusters_saved=total_clusters_saved if not dry_run else 0,
        )

    def run_once(self, limit: int = 10) -> ContinuousRunResult:
        """运行一次处理（用于测试或手动触发）

        Args:
            limit: 处理文章数量上限

        Returns:
            ContinuousRunResult: 处理结果
        """
        # 临时修改 batch_size
        original_batch_size = self.batch_size
        self.batch_size = limit

        result = self.run()

        self.batch_size = original_batch_size
        return result


def run_continuous(
    batch_size: int = 10,
    graph_enabled: bool = True,
    incremental: bool = True,
    time_window: str | None = None,
    dry_run: bool = False,
) -> ContinuousRunResult:
    """持续运行模式便捷入口

    Args:
        batch_size: 每批处理数量
        graph_enabled: 是否启用图谱同步
        incremental: 是否增量处理
        time_window: 时间切片过滤
        dry_run: 仅测试

    Returns:
        ContinuousRunResult: 处理结果
    """
    pipeline = ContinuousPipeline(
        batch_size=batch_size,
        graph_enabled=graph_enabled,
        incremental=incremental,
    )
    return pipeline.run(time_window=time_window, dry_run=dry_run)
