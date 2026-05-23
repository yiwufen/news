"""Offline continuous pipeline entrypoint."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from src.retrieval.vector_index import VectorIndex

from src.entities import Entity, EntityRepository, EntityResolver, is_valid_entity_mention
from src.entity_context_filter import filter_relevant_entities
from src.event_merging import EventCluster, EventClusterRepository, EventMerger
from src.knowledge_base import (
    KnowledgeProcessingLogRepository,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    RawDocumentRepository,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.retrieval.indexing import KnowledgeIndexBuilder

logger = logging.getLogger(__name__)

ProcessingStage = Literal["extract", "resolve", "cluster", "save", "index", "complete"]


@dataclass
class DocumentProcessingResult:
    """单个文档的处理结果。"""

    doc_id: str
    status: Literal["success", "partial", "failed"]
    failed_stage: ProcessingStage | None
    error_message: str | None
    units: list[KnowledgeUnit] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    clusters: list[EventCluster] = field(default_factory=list)

    @property
    def knowledge_units_count(self) -> int:
        return len(self.units)

    @property
    def entities_count(self) -> int:
        return len(self.entities)

    @property
    def clusters_count(self) -> int:
        return len(self.clusters)


@dataclass
class BatchProcessingContext:
    """Batch 级别的处理上下文，缓存跨文档共享的数据。"""

    entities_cache: dict[str, Entity] = field(default_factory=dict)
    clusters_cache: dict[str, EventCluster] = field(default_factory=dict)
    cluster_members_cache: dict[str, list[KnowledgeUnit]] = field(default_factory=dict)
    results: list[DocumentProcessingResult] = field(default_factory=list)


@dataclass
class ContinuousRunResult:
    """Result of one continuous run."""

    nodes_created: int
    edges_created: int
    errors: list[str]
    knowledge_units_extracted: int = 0
    knowledge_units_saved: int = 0
    entities_saved: int = 0
    clusters_saved: int = 0


class ContinuousPipeline:
    """RawDocument -> KnowledgeUnit -> Entity/EventCluster -> graph sync."""

    def __init__(
        self,
        batch_size: int = 10,
        graph_enabled: bool = True,
        incremental: bool = True,
        db_path: str = "data/news.db",
        extractor: KnowledgeExtractor | None = None,
        index_builder: KnowledgeIndexBuilder | None = None,
        vector_index: VectorIndex | None = None,
    ):
        self.batch_size = batch_size
        self.graph_enabled = graph_enabled
        self.incremental = incremental
        self.raw_documents = RawDocumentRepository(db_path)
        self.knowledge_units = KnowledgeUnitRepository(db_path)
        self.entity_repo = EntityRepository(db_path)
        self.cluster_repo = EventClusterRepository(
            db_path,
            knowledge_units=self.knowledge_units,
        )
        self.log_repo = KnowledgeProcessingLogRepository(db_path)
        self.extractor = extractor or KnowledgeExtractor()
        self._embedding_provider = self._try_create_embedding_provider()
        self._description_generator = self._try_create_description_generator()
        # Shared vector index — same instance for clusterer and index_builder
        self._vector_index = vector_index or self._try_create_vector_index()
        self.entity_resolver = EntityResolver(
            self.entity_repo,
            embedding_provider=self._embedding_provider,
            description_generator=self._description_generator,
        )
        self.clusterer = EventMerger(
            self.cluster_repo,
            knowledge_units=self.knowledge_units,
            embedding_provider=self._embedding_provider,
            vector_index=self._vector_index,
        )
        self.graph_sync = KnowledgeGraphSync() if graph_enabled else None
        self.index_builder = index_builder or KnowledgeIndexBuilder(
            self.knowledge_units,
            vector_index=self._vector_index,
        )
        logger.info(f"ContinuousPipeline initialized (batch_size={batch_size}, graph_enabled={graph_enabled}, incremental={incremental})")

    @staticmethod
    def _try_create_embedding_provider():
        """Attempt to create an embedding provider. Returns None on failure."""
        try:
            from src.retrieval.embedding import OpenAICompatEmbedding
            return OpenAICompatEmbedding()
        except Exception:
            logger.info("Entity disambiguation disabled (no embedding config)")
            return None

    def _try_create_vector_index(self):
        """Create a VectorIndex if embedding is configured. Returns None on failure."""
        try:
            if self._embedding_provider is None:
                return None
            from src.retrieval.vector_index import VectorIndex
            return VectorIndex("data/news.db", self._embedding_provider)
        except Exception:
            logger.info("Vector index disabled (no embedding config)")
            return None

    @staticmethod
    def _try_create_description_generator():
        """Attempt to create an entity description generator. Returns None on failure."""
        try:
            from src.entity_description import EntityDescriptionGenerator
            return EntityDescriptionGenerator(enable=True)
        except Exception:
            logger.info("Entity description generation disabled")
            return None

    def run(
        self,
        time_window: str | None = None,
        dry_run: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ContinuousRunResult:
        logger.info(f"Starting pipeline run (time_window={time_window}, dry_run={dry_run})")
        all_errors: list[str] = []
        all_units: list[KnowledgeUnit] = []
        total_nodes = 0
        total_edges = 0
        total_entities_saved = 0
        total_clusters_saved = 0
        batch_count = 0
        docs_done = 0

        for batch, total in self.raw_documents.iter_documents(
            batch_size=self.batch_size,
            time_window=time_window,
            incremental=self.incremental,
        ):
            batch_count += 1
            logger.debug(f"Processing batch {batch_count} with {len(batch)} documents")

            # Batch 初始化：加载全量实体缓存（resolve_units 需要）
            context = BatchProcessingContext(
                entities_cache={
                    entity.entity_id: entity for entity in self.entity_repo.get_all()
                },
                clusters_cache={},  # _find_cluster 改为查 DB，无需预加载
            )

            # 文档级独立处理
            for document in batch:
                result = self._process_single_document(
                    document=document,
                    context=context,
                    dry_run=dry_run,
                )
                context.results.append(result)

                # 收集成功的产出
                if result.status in ("success", "partial"):
                    all_units.extend(result.units)
                    total_entities_saved += result.entities_count
                    total_clusters_saved += result.clusters_count

                # 收集错误
                if result.error_message:
                    all_errors.append(f"[{document.doc_id}] {result.error_message}")

            # 后处理：图同步
            if not dry_run and self.graph_enabled and self.graph_sync:
                all_entities = [
                    entity for r in context.results for entity in r.entities
                ]
                all_clusters = [
                    cluster for r in context.results for cluster in r.clusters
                ]
                if all_entities or all_clusters:
                    try:
                        sync_result = self.graph_sync.sync(all_entities, all_clusters)
                        total_nodes += sync_result["entities_created"] + sync_result["clusters_created"]
                        total_edges += sync_result["edges_created"]
                        all_errors.extend(sync_result["errors"])
                    except Exception as exc:
                        all_errors.append(f"[graph_sync] {exc}")
                        logger.error(f"Graph sync failed: {exc}")

            # 记录日志
            if not dry_run:
                log_records = [
                    {
                        "doc_id": r.doc_id,
                        "status": r.status,
                        "knowledge_units_count": r.knowledge_units_count,
                        "entities_count": r.entities_count,
                        "clusters_count": r.clusters_count,
                        "error_message": r.error_message,
                    }
                    for r in context.results
                ]
                self.log_repo.log_batch(log_records)

            docs_done += len(batch)
            if on_progress:
                on_progress(docs_done, total)

        result = ContinuousRunResult(
            nodes_created=total_nodes,
            edges_created=total_edges,
            errors=all_errors,
            knowledge_units_extracted=len(all_units),
            knowledge_units_saved=len(all_units) if not dry_run else 0,
            entities_saved=total_entities_saved if not dry_run else 0,
            clusters_saved=total_clusters_saved if not dry_run else 0,
        )
        logger.info(
            f"Pipeline run completed: {result.knowledge_units_extracted} units extracted, "
            f"{result.nodes_created} nodes, {result.edges_created} edges"
        )
        if all_errors:
            logger.warning(f"Pipeline completed with {len(all_errors)} errors")
        return result

    def _process_single_document(
        self,
        document: RawDocument,
        context: BatchProcessingContext,
        dry_run: bool,
    ) -> DocumentProcessingResult:
        """
        处理单个文档，每个阶段独立 try-except。

        使用 context 中的缓存进行实体解析和集群分配。
        """
        result = DocumentProcessingResult(
            doc_id=document.doc_id,
            status="failed",
            failed_stage=None,
            error_message=None,
        )

        # Stage 1: Extract (with entity context)
        try:
            entity_context = filter_relevant_entities(
                document=document,
                all_entities=context.entities_cache,
                max_entities=50,
                max_tokens_estimate=2000,
            )
            units = self.extractor.extract(document, entity_context=entity_context)
            result.units = units
        except Exception as exc:
            result.failed_stage = "extract"
            result.error_message = f"extract failed: {exc}"
            logger.error(f"[{document.doc_id}] Extract failed: {exc}")
            return result

        if not units:
            result.status = "success"
            result.failed_stage = "complete"
            return result

        # Post-extraction: normalize unit_type, filter invalid entity mentions
        from src.schemas.enums import normalize_unit_type

        valid_units: list[KnowledgeUnit] = []
        for unit in units:
            # Normalize unit_type to canonical vocabulary
            unit.unit_type = normalize_unit_type(unit.unit_type).value
            # Filter invalid entity mentions, redirect to tags
            valid_entities = []
            for entity_ref in unit.entities:
                if is_valid_entity_mention(entity_ref.mention):
                    valid_entities.append(entity_ref)
                elif entity_ref.mention.strip() not in unit.tags:
                    unit.tags.append(entity_ref.mention.strip())
            unit.entities = valid_entities
            valid_units.append(unit)
        units = valid_units
        result.units = units

        if not units:
            result.status = "success"
            result.failed_stage = "complete"
            return result

        # Stage 2: Resolve Entities (defer persist until KUs are saved)
        try:
            resolved_units, resolved_entities = self.entity_resolver.resolve_units_with_cache(
                units=units,
                entities_cache=context.entities_cache,
                persist=False,
            )
            result.units = resolved_units
            result.entities = resolved_entities

            # Backfill relation_hints: map mention → entity_id
            # This must run after entity resolution so entity_ids are populated
            for unit in resolved_units:
                entity_mention_map: dict[str, str] = {
                    e.mention: e.entity_id
                    for e in unit.entities
                    if e.entity_id
                }
                for rh in unit.relation_hints:
                    if rh.subject_mention:
                        rh.subject_entity_id = entity_mention_map.get(rh.subject_mention)
                    if rh.object_mention:
                        rh.object_entity_id = entity_mention_map.get(rh.object_mention)
            # Remove relation_hints with unresolvable mentions
            for unit in resolved_units:
                unit.relation_hints = [
                    rh for rh in unit.relation_hints
                    if rh.subject_entity_id or rh.object_entity_id
                ]

            # 更新缓存，使后续文档可见新实体
            for entity in resolved_entities:
                context.entities_cache[entity.entity_id] = entity
        except Exception as exc:
            result.failed_stage = "resolve"
            result.error_message = f"resolve failed: {exc}"
            logger.error(f"[{document.doc_id}] Resolve failed: {exc}")
            return result

        # Stage 3: Assign Clusters (defer persist until KUs are saved)
        try:
            clustered_units, clusters = self.clusterer.assign_clusters_with_cache(
                units=resolved_units,
                clusters_cache=context.clusters_cache,
                cluster_members_cache=context.cluster_members_cache,
                persist=False,
            )
            result.units = clustered_units
            result.clusters = clusters

            # 更新缓存
            for cluster in clusters:
                context.clusters_cache[cluster.cluster_id] = cluster
        except Exception as exc:
            result.failed_stage = "cluster"
            result.error_message = f"cluster failed: {exc}"
            logger.error(f"[{document.doc_id}] Cluster failed: {exc}")
            return result

        # Stage 4: Persist KUs first, then entities and clusters
        if not dry_run:
            try:
                self.knowledge_units.save_batch(clustered_units)
                self.entity_repo.save_batch(resolved_entities)
                self.cluster_repo.save_batch(clusters)
            except Exception as exc:
                result.failed_stage = "save"
                result.error_message = f"save failed: {exc}"
                logger.error(f"[{document.doc_id}] Save failed: {exc}")
                return result

        # Stage 5: Index
        indexing_error = None
        if not dry_run:
            try:
                self.index_builder.build_for_units(clustered_units)
            except Exception as exc:
                indexing_error = f"index failed: {exc}"
                logger.error(f"[{document.doc_id}] Index failed: {exc}")

        # 确定最终状态
        # 索引失败不影响文档处理成功状态，因为知识单元已成功保存
        if indexing_error:
            result.status = "success"
            result.error_message = indexing_error
        else:
            result.status = "success"
            result.failed_stage = "complete"

        return result

    def run_once(self, limit: int = 10) -> ContinuousRunResult:
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
    db_path: str = "data/news.db",
    on_progress: Callable[[int, int], None] | None = None,
) -> ContinuousRunResult:
    """Convenience entrypoint for the continuous pipeline."""
    from src.retrieval.indexing import KnowledgeIndexBuilder, try_create_vector_index

    ku_repo = KnowledgeUnitRepository(db_path)
    vector_index = try_create_vector_index(db_path)
    index_builder = KnowledgeIndexBuilder(ku_repo, vector_index=vector_index)

    pipeline = ContinuousPipeline(
        batch_size=batch_size,
        graph_enabled=graph_enabled,
        incremental=incremental,
        db_path=db_path,
        index_builder=index_builder,
        vector_index=vector_index,
    )
    return pipeline.run(time_window=time_window, dry_run=dry_run, on_progress=on_progress)
