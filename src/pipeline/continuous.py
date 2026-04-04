"""
Offline continuous pipeline entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.entities import EntityResolver, EntityRepository
from src.event_clustering import EventClusterRepository, EventClusterer
from src.knowledge_base import (
    KnowledgeProcessingLogRepository,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocumentRepository,
    compute_slice_window_from_datetime,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.retrieval.indexing import KnowledgeIndexBuilder


def _build_legacy_particle(unit: KnowledgeUnit) -> dict[str, Any]:
    """Build a compatibility payload for legacy callers of `run_continuous()`."""
    anchor = unit.time.event_time or unit.time.published_at
    return {
        "particle_id": unit.ku_id,
        "slice_window": compute_slice_window_from_datetime(anchor),
        "event_type": unit.unit_type,
        "event_summary": unit.summary,
        "entities": [entity.mention for entity in unit.entities],
        "source_doc_ids": [unit.source.doc_id],
    }


@dataclass
class ContinuousRunResult:
    """Result of one continuous run."""

    nodes_created: int
    edges_created: int
    errors: list[str]
    particles_extracted: int = 0
    particles_saved: int = 0
    particles: list[dict[str, Any]] = field(default_factory=list)
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
    ):
        self.batch_size = batch_size
        self.graph_enabled = graph_enabled
        self.incremental = incremental
        self.raw_documents = RawDocumentRepository(db_path)
        self.knowledge_units = KnowledgeUnitRepository(db_path)
        self.entity_repo = EntityRepository(db_path)
        self.cluster_repo = EventClusterRepository(db_path)
        self.log_repo = KnowledgeProcessingLogRepository(db_path)
        self.extractor = extractor or KnowledgeExtractor()
        self.entity_resolver = EntityResolver(self.entity_repo)
        self.clusterer = EventClusterer(self.cluster_repo)
        self.graph_sync = KnowledgeGraphSync() if graph_enabled else None
        self.index_builder = index_builder or KnowledgeIndexBuilder(
            self.knowledge_units,
            self.entity_repo,
        )

    def run(
        self,
        time_window: str | None = None,
        dry_run: bool = False,
    ) -> ContinuousRunResult:
        errors: list[str] = []
        all_units: list[KnowledgeUnit] = []
        legacy_particles: list[dict[str, Any]] = []
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
                    errors.append(f"[{document.doc_id}] KnowledgeUnit extraction failed: {exc}")
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
            legacy_particles.extend(_build_legacy_particle(unit) for unit in clustered_units)

            indexing_errors: list[str] = []
            post_processing_errors: list[str] = []
            if not dry_run:
                self.knowledge_units.save_batch(clustered_units)
                try:
                    self.index_builder.build_for_units(clustered_units)
                except Exception as exc:
                    indexing_errors.append(str(exc))
                    errors.append(f"[index] {exc}")

                if self.graph_enabled and self.graph_sync:
                    sync_result = self.graph_sync.sync(resolved_entities, clusters)
                    total_nodes += sync_result["entities_created"] + sync_result["clusters_created"]
                    total_edges += sync_result["edges_created"]
                    errors.extend(sync_result["errors"])
                    if sync_result["errors"]:
                        post_processing_errors.extend(sync_result["errors"])

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
                blocking_errors = list(post_processing_errors)
                error_details = list(blocking_errors)
                error_details.extend(error for error in indexing_errors if error not in error_details)
                error_message = "; ".join(error_details) if error_details else None
                status = "failed" if blocking_errors else "success"
                batch_log_records.append(
                    {
                        "doc_id": document.doc_id,
                        "status": status,
                        "knowledge_units_count": len(doc_units),
                        "entities_count": len(entities_by_doc.get(document.doc_id, set())),
                        "clusters_count": len(clusters_by_doc.get(document.doc_id, set())),
                        "error_message": error_message,
                    }
                )

            if not dry_run:
                self.log_repo.log_batch(batch_log_records)

        return ContinuousRunResult(
            nodes_created=total_nodes,
            edges_created=total_edges,
            errors=errors,
            particles_extracted=len(legacy_particles),
            particles_saved=len(legacy_particles) if not dry_run else 0,
            particles=legacy_particles,
            knowledge_units_extracted=len(all_units),
            knowledge_units_saved=len(all_units) if not dry_run else 0,
            entities_saved=total_entities_saved if not dry_run else 0,
            clusters_saved=total_clusters_saved if not dry_run else 0,
        )

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
) -> ContinuousRunResult:
    """Convenience entrypoint for the continuous pipeline."""
    pipeline = ContinuousPipeline(
        batch_size=batch_size,
        graph_enabled=graph_enabled,
        incremental=incremental,
    )
    return pipeline.run(time_window=time_window, dry_run=dry_run)
