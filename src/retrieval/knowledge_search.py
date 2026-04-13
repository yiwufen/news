"""
Knowledge-centric BM25 retrieval over KnowledgeUnit, Entity, and EventCluster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from src.entities import (
    Entity,
    EntityRepository,
    EntityResolver,
    build_entity_name_variants,
)
from src.event_clustering import EventCluster, EventClusterRepository, EventClusterer
from src.schemas.query import StructuredQuery
from src.knowledge_base import (
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    adapt_article_to_raw_document,
    build_knowledge_unit_search_text,
)
from src.knowledge_extractor import KnowledgeExtractor


@dataclass
class KnowledgeSearchRequest:
    structured_query: StructuredQuery
    top_k: int = 20


@dataclass
class KnowledgeSearchResult:
    knowledge_units: list[KnowledgeUnit]
    entities: list[Entity]
    event_clusters: list[EventCluster]
    total_count: int
    bm25_count: int = 0
    applied_filters: dict[str, object] = field(default_factory=dict)
    hit_scores: dict[str, dict[str, object]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_units": [unit.model_dump(mode="json") for unit in self.knowledge_units],
            "entities": [entity.model_dump(mode="json") for entity in self.entities],
            "event_clusters": [cluster.model_dump(mode="json") for cluster in self.event_clusters],
            "total_count": self.total_count,
            "retrieval": {
                "retrieval_mode": "bm25",
                "bm25_count": self.bm25_count,
                "applied_filters": self.applied_filters,
                "hit_scores": self.hit_scores,
            },
        }


class KnowledgeSearcher:
    """Search the normalized knowledge store via BM25 + structured filtering."""

    def __init__(
        self,
        db_path: str = "data/news.db",
        extractor: KnowledgeExtractor | None = None,
    ):
        self.units = KnowledgeUnitRepository(db_path)
        self.entities = EntityRepository(db_path)
        self.clusters = EventClusterRepository(
            db_path,
            knowledge_units=self.units,
        )
        self.extractor = extractor or KnowledgeExtractor()
        self.entity_resolver = EntityResolver(self.entities)
        self.clusterer = EventClusterer(
            self.clusters,
            knowledge_units=self.units,
        )

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        query = request.structured_query
        matched_entities = self.entities.find_by_names(query.entities)
        entity_id_filter = [entity.entity_id for entity in matched_entities]
        if query.entities and not entity_id_filter:
            return self._empty_result(request, matched_entities)

        time_range = self._serialize_time_range(query)
        event_types = query.filters.event_types or None
        candidate_limit = max(request.top_k * 3, request.top_k)

        bm25_hits = self.units.search_bm25(
            self._build_fts_query(query, matched_entities),
            top_k=candidate_limit,
            time_range=time_range,
            event_types=event_types,
            entity_ids=entity_id_filter or None,
        )

        return self._build_ranked_result(
            request=request,
            bm25_hits=bm25_hits,
            matched_entities=matched_entities,
        )

    def search_articles(
        self,
        articles: list[dict],
        request: KnowledgeSearchRequest,
    ) -> KnowledgeSearchResult:
        raw_documents: list[RawDocument] = [
            adapt_article_to_raw_document(article)
            for article in articles
        ]
        extracted_units: list[KnowledgeUnit] = []
        for document in raw_documents:
            extracted_units.extend(self.extractor.extract(document))
        resolved_units, transient_entities = self.entity_resolver.resolve_units(
            extracted_units,
            persist=False,
        )
        clustered_units, transient_clusters = self.clusterer.assign_clusters(
            resolved_units,
            persist=False,
        )
        return self._search_units_in_memory(
            clustered_units,
            request,
            transient_entities=transient_entities,
            transient_clusters=transient_clusters,
        )

    def _empty_result(
        self,
        request: KnowledgeSearchRequest,
        matched_entities: list[Entity],
    ) -> KnowledgeSearchResult:
        return KnowledgeSearchResult(
            knowledge_units=[],
            entities=matched_entities,
            event_clusters=[],
            total_count=0,
            applied_filters=self._build_applied_filters(
                request.structured_query,
                matched_entities,
            ),
        )

    def _build_ranked_result(
        self,
        *,
        request: KnowledgeSearchRequest,
        bm25_hits: list[tuple[str, float]],
        matched_entities: list[Entity],
    ) -> KnowledgeSearchResult:
        candidate_ids = [ku_id for ku_id, _ in bm25_hits]
        if not candidate_ids:
            return self._empty_result(request, matched_entities)

        unit_map = {
            unit.ku_id: unit
            for unit in self.units.get_by_ids(candidate_ids)
        }
        bm25_lookup = dict(bm25_hits)
        ranked_hits: list[tuple[float, KnowledgeUnit, dict[str, object]]] = []
        matched_entity_ids = {entity.entity_id for entity in matched_entities}

        for ku_id in candidate_ids:
            unit = unit_map.get(ku_id)
            if unit is None:
                continue
            final_score, metadata = self._score_final_hit(
                unit,
                request.structured_query,
                bm25_lookup.get(ku_id, 0.0),
                matched_entity_ids=matched_entity_ids,
            )
            ranked_hits.append((final_score, unit, metadata))

        ranked_hits.sort(
            key=lambda item: (
                item[0],
                self._unit_anchor(item[1]).timestamp(),
                item[1].ku_id,
            ),
            reverse=True,
        )
        selected = ranked_hits[: request.top_k]
        selected_units = [unit for _, unit, _ in selected]
        selected_unit_ids = [unit.ku_id for unit in selected_units]
        selected_entity_ids = {
            entity.entity_id
            for unit in selected_units
            for entity in unit.entities
            if entity.entity_id
        } | matched_entity_ids
        selected_cluster_ids = {
            unit.cluster_id for unit in selected_units if unit.cluster_id
        }

        selected_entities = self.entities.get_by_ids(selected_entity_ids)
        related_clusters = self.clusters.find_related(
            primary_entity_ids=selected_entity_ids,
            cluster_types=request.structured_query.filters.event_types,
            time_range=self._serialize_time_range(request.structured_query),
        )
        related_cluster_ids = {cluster.cluster_id for cluster in related_clusters}
        selected_clusters = self.clusters.get_by_ids(list(selected_cluster_ids | related_cluster_ids))

        hit_scores = {
            unit.ku_id: metadata
            for _, unit, metadata in selected
        }
        return KnowledgeSearchResult(
            knowledge_units=selected_units,
            entities=selected_entities,
            event_clusters=selected_clusters,
            total_count=len(ranked_hits),
            bm25_count=len(bm25_hits),
            applied_filters=self._build_applied_filters(
                request.structured_query,
                matched_entities,
            ),
            hit_scores=hit_scores,
        )

    def _search_units_in_memory(
        self,
        all_units: list[KnowledgeUnit],
        request: KnowledgeSearchRequest,
        transient_entities: list[Entity] | None = None,
        transient_clusters: list[EventCluster] | None = None,
    ) -> KnowledgeSearchResult:
        all_entities = transient_entities or []
        all_clusters = transient_clusters or []
        entity_map = {entity.entity_id: entity for entity in all_entities}
        ranked: list[tuple[float, KnowledgeUnit]] = []
        for unit in all_units:
            if not self._matches_time(unit, request.structured_query):
                continue
            if request.structured_query.entities and not self._matches_entities(
                unit,
                request.structured_query.entities,
                entity_map,
            ):
                continue
            score = self._score_in_memory_unit(unit, request.structured_query, entity_map)
            ranked.append((score, unit))

        ranked.sort(
            key=lambda item: (
                item[0],
                self._unit_anchor(item[1]).timestamp(),
                item[1].ku_id,
            ),
            reverse=True,
        )
        selected_units = [unit for _, unit in ranked[: request.top_k]]
        selected_entity_ids = {
            entity.entity_id
            for unit in selected_units
            for entity in unit.entities
            if entity.entity_id
        }
        selected_cluster_ids = {
            unit.cluster_id for unit in selected_units if unit.cluster_id
        }
        selected_entities = [
            entity for entity in all_entities if entity.entity_id in selected_entity_ids
        ]
        selected_clusters = [
            cluster for cluster in all_clusters if cluster.cluster_id in selected_cluster_ids
        ]
        return KnowledgeSearchResult(
            knowledge_units=selected_units,
            entities=selected_entities,
            event_clusters=selected_clusters,
            total_count=len(ranked),
            bm25_count=len(selected_units),
            applied_filters=self._build_applied_filters(request.structured_query, selected_entities),
            hit_scores={
                unit.ku_id: {
                    "score": score,
                    "sources": ["memory"],
                    "component_scores": {"memory": score},
                }
                for score, unit in ranked[: request.top_k]
            },
        )

    def _build_fts_query(
        self,
        query: StructuredQuery,
        matched_entities: list[Entity],
    ) -> str:
        terms: list[str] = []
        for token in self._tokenize_query(query.original_query.lower()):
            terms.append(token)
        for entity in matched_entities:
            for name in [entity.canonical_name, *entity.aliases]:
                terms.extend(self._tokenize_query(name.lower()))
                if name.strip():
                    terms.append(self._quote_fts_phrase(name.strip()))
        for event_type in query.filters.event_types or []:
            terms.extend(self._tokenize_query(event_type.lower()))
        unique_terms = list(dict.fromkeys(term for term in terms if term))
        return " OR ".join(unique_terms)

    def _score_final_hit(
        self,
        unit: KnowledgeUnit,
        query: StructuredQuery,
        bm25_score: float,
        *,
        matched_entity_ids: set[str],
    ) -> tuple[float, dict[str, object]]:
        # 分层权重：实体匹配(5x) > 类型匹配(2x) > 文本匹配(bm25) > 时效(tiny)
        component_scores: dict[str, float] = {"bm25_score": bm25_score}
        final_score = bm25_score

        unit_entity_ids = {
            entity.entity_id for entity in unit.entities if entity.entity_id
        }
        if matched_entity_ids and unit_entity_ids & matched_entity_ids:
            component_scores["entity_bonus"] = 5.0
            final_score += 5.0
        if query.filters.event_types and unit.unit_type in query.filters.event_types:
            component_scores["event_type_bonus"] = 2.0
            final_score += 2.0
        recency_bonus = self._unit_anchor(unit).timestamp() / 10_000_000_000_000
        component_scores["recency_bonus"] = recency_bonus
        final_score += recency_bonus
        metadata = {
            "score": final_score,
            "sources": ["bm25"],
            "component_scores": component_scores,
        }
        return final_score, metadata

    def _build_applied_filters(
        self,
        query: StructuredQuery,
        matched_entities: list[Entity],
    ) -> dict[str, object]:
        return {
            "entities": query.entities,
            "matched_entity_ids": [entity.entity_id for entity in matched_entities],
            "time_range": query.time_range.to_dict() if query.time_range else None,
            "event_types": query.filters.event_types or [],
        }

    def _matches_time(self, unit: KnowledgeUnit, query: StructuredQuery) -> bool:
        if query.time_range is None:
            return True
        anchor = self._unit_anchor(unit).date()
        return query.time_range.start <= anchor <= query.time_range.end

    def _matches_entities(
        self,
        unit: KnowledgeUnit,
        query_entities: list[str],
        entity_map: dict[str, Entity],
    ) -> bool:
        unit_variants = self._unit_entity_variants(unit, entity_map)
        if not unit_variants:
            return False
        return any(self._query_entity_variants(entity) & unit_variants for entity in query_entities)

    def _score_in_memory_unit(
        self,
        unit: KnowledgeUnit,
        query: StructuredQuery,
        entity_map: dict[str, Entity],
    ) -> float:
        unit_variants = self._unit_entity_variants(unit, entity_map)
        haystack = self._unit_search_text(unit, entity_map)
        score = 0.0

        if query.entities:
            for entity in query.entities:
                if self._query_entity_variants(entity) & unit_variants:
                    score += 5.0

        if query.filters.event_types and unit.unit_type in query.filters.event_types:
            score += 2.0

        raw_query = query.original_query.strip().lower()
        if raw_query:
            if raw_query in haystack:
                score += 3.0
            else:
                for token in self._tokenize_query(raw_query):
                    if token in haystack:
                        score += 0.5

        score += self._unit_anchor(unit).timestamp() / 10_000_000_000
        return score

    def _unit_search_text(
        self,
        unit: KnowledgeUnit,
        entity_map: dict[str, Entity],
    ) -> str:
        entity_names: list[str] = []
        for entity_ref in unit.entities:
            entity_names.append(entity_ref.mention)
            if not entity_ref.entity_id:
                continue
            entity = entity_map.get(entity_ref.entity_id)
            if entity:
                entity_names.append(entity.canonical_name)
                entity_names.extend(entity.aliases)
        return build_knowledge_unit_search_text(unit, entity_names=entity_names).lower()

    def _unit_entity_variants(
        self,
        unit: KnowledgeUnit,
        entity_map: dict[str, Entity],
    ) -> set[str]:
        variants: set[str] = set()
        for entity_ref in unit.entities:
            variants |= build_entity_name_variants(entity_ref.mention)
            if entity_ref.entity_id and entity_ref.entity_id in entity_map:
                entity = entity_map[entity_ref.entity_id]
                variants |= build_entity_name_variants(entity.canonical_name, *entity.aliases)
        return variants

    def _query_entity_variants(self, entity_name: str) -> set[str]:
        return build_entity_name_variants(entity_name)

    def _serialize_time_range(self, query: StructuredQuery) -> tuple[str, str] | None:
        if query.time_range is None:
            return None
        return (
            query.time_range.start.isoformat(),
            query.time_range.end.isoformat(),
        )

    def _tokenize_query(self, raw_query: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{2,}", raw_query)
        return [token for token in tokens if len(token) >= 2]

    def _quote_fts_phrase(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _unit_anchor(self, unit: KnowledgeUnit) -> datetime:
        return unit.time.event_time or unit.time.published_at
