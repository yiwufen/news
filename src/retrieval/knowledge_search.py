"""
Knowledge-centric hybrid retrieval over KnowledgeUnit, Entity, and EventCluster.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from src.entities import (
    Entity,
    EntityRepository,
    EntityResolver,
    build_entity_name_variants,
)
from src.event_clustering import EventCluster, EventClusterRepository, EventClusterer
from src.intent.models import StructuredQuery
from src.knowledge_base import (
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    adapt_article_to_raw_document,
    build_knowledge_unit_search_text,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.retrieval.embedding_client import EmbeddingClient, OpenAIEmbeddingClient


RetrievalMode = Literal["hybrid", "bm25_only", "vector_only"]


@dataclass
class KnowledgeSearchRequest:
    structured_query: StructuredQuery
    top_k: int = 20
    retrieval_mode: RetrievalMode = "hybrid"


@dataclass
class KnowledgeSearchResult:
    knowledge_units: list[KnowledgeUnit]
    entities: list[Entity]
    event_clusters: list[EventCluster]
    total_count: int
    retrieval_mode: str
    bm25_count: int = 0
    vector_count: int = 0
    fusion_count: int = 0
    applied_filters: dict[str, object] = field(default_factory=dict)
    hit_scores: dict[str, dict[str, object]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_units": [unit.model_dump(mode="json") for unit in self.knowledge_units],
            "entities": [entity.model_dump(mode="json") for entity in self.entities],
            "event_clusters": [cluster.model_dump(mode="json") for cluster in self.event_clusters],
            "total_count": self.total_count,
            "retrieval": {
                "retrieval_mode": self.retrieval_mode,
                "bm25_count": self.bm25_count,
                "vector_count": self.vector_count,
                "fusion_count": self.fusion_count,
                "applied_filters": self.applied_filters,
                "hit_scores": self.hit_scores,
            },
        }


class KnowledgeSearcher:
    """Search the normalized knowledge store instead of legacy particles."""

    def __init__(
        self,
        db_path: str = "data/news.db",
        extractor: KnowledgeExtractor | None = None,
        embedding_client: EmbeddingClient | None = None,
    ):
        self.units = KnowledgeUnitRepository(db_path)
        self.entities = EntityRepository(db_path)
        self.clusters = EventClusterRepository(
            db_path,
            knowledge_units=self.units,
        )
        self.extractor = extractor or KnowledgeExtractor()
        self.embedding_client = embedding_client or OpenAIEmbeddingClient()
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
        candidate_limit = max(request.top_k * 5, request.top_k)

        bm25_hits: list[tuple[str, float]] = []
        if request.retrieval_mode in ("hybrid", "bm25_only"):
            match_query = self._build_fts_query(query, matched_entities)
            bm25_hits = self.units.search_bm25(
                match_query,
                top_k=candidate_limit,
                time_range=time_range,
                event_types=event_types,
                entity_ids=entity_id_filter or None,
            )

        vector_hits: list[tuple[str, float]] = []
        if request.retrieval_mode in ("hybrid", "vector_only"):
            vector_hits = self._vector_search(
                query,
                matched_entities=matched_entities,
                top_k=candidate_limit,
                time_range=time_range,
                event_types=event_types,
                entity_ids=entity_id_filter or None,
            )

        return self._build_ranked_result(
            request=request,
            bm25_hits=bm25_hits,
            vector_hits=vector_hits,
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
            retrieval_mode=request.retrieval_mode,
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
        vector_hits: list[tuple[str, float]],
        matched_entities: list[Entity],
    ) -> KnowledgeSearchResult:
        candidate_ids = list(
            dict.fromkeys([ku_id for ku_id, _ in bm25_hits] + [ku_id for ku_id, _ in vector_hits])
        )
        if not candidate_ids:
            return self._empty_result(request, matched_entities)

        unit_map = {
            unit.ku_id: unit
            for unit in self.units.get_by_ids(candidate_ids)
        }
        fusion_scores = self._fuse_hits(bm25_hits, vector_hits)
        ranked_hits: list[tuple[float, KnowledgeUnit, dict[str, object]]] = []
        matched_entity_ids = {entity.entity_id for entity in matched_entities}

        for ku_id in candidate_ids:
            unit = unit_map.get(ku_id)
            if unit is None:
                continue
            final_score, metadata = self._score_final_hit(
                unit,
                request.structured_query,
                fusion_scores.get(ku_id, 0.0),
                bm25_hits=bm25_hits,
                vector_hits=vector_hits,
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
            retrieval_mode=request.retrieval_mode,
            bm25_count=len(bm25_hits),
            vector_count=len(vector_hits),
            fusion_count=len(selected_unit_ids),
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
            retrieval_mode=request.retrieval_mode,
            fusion_count=len(selected_units),
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

    def _vector_search(
        self,
        query: StructuredQuery,
        *,
        matched_entities: list[Entity],
        top_k: int,
        time_range: tuple[str, str] | None,
        event_types: list[str] | None,
        entity_ids: list[str] | None,
    ) -> list[tuple[str, float]]:
        query_text = self._build_query_embedding_text(query, matched_entities)
        query_embedding = self.embedding_client.embed_texts([query_text])[0]
        if not query_embedding:
            raise RuntimeError("embedding API returned an empty query embedding")

        embedding_model = getattr(self.embedding_client, "model", None)
        indexed_embeddings = self.units.get_embeddings(
            time_range=time_range,
            event_types=event_types,
            entity_ids=entity_ids,
            embedding_model=embedding_model,
        )
        if not indexed_embeddings:
            return []

        scored: list[tuple[str, float]] = []
        expected_dim = len(query_embedding)
        for indexed in indexed_embeddings:
            if indexed.embedding_dim != expected_dim or len(indexed.embedding) != expected_dim:
                raise RuntimeError("embedding index contains incompatible embedding dimensions")
            scored.append((indexed.ku_id, self._cosine_similarity(query_embedding, indexed.embedding)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

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

    def _build_query_embedding_text(
        self,
        query: StructuredQuery,
        matched_entities: list[Entity],
    ) -> str:
        pieces = [query.original_query.strip()]
        if query.entities:
            pieces.append("entities: " + ", ".join(query.entities))
        if matched_entities:
            pieces.append(
                "entity_variants: "
                + ", ".join(
                    dict.fromkeys(
                        name
                        for entity in matched_entities
                        for name in [entity.canonical_name, *entity.aliases]
                        if name
                    )
                )
            )
        if query.filters.event_types:
            pieces.append("event_types: " + ", ".join(query.filters.event_types))
        return "\n".join(piece for piece in pieces if piece).strip()

    def _fuse_hits(
        self,
        bm25_hits: list[tuple[str, float]],
        vector_hits: list[tuple[str, float]],
    ) -> dict[str, float]:
        fused: dict[str, float] = {}
        for hits in (bm25_hits, vector_hits):
            for rank, (ku_id, _) in enumerate(hits, start=1):
                fused[ku_id] = fused.get(ku_id, 0.0) + (1.0 / (60 + rank))
        return fused

    def _score_final_hit(
        self,
        unit: KnowledgeUnit,
        query: StructuredQuery,
        fusion_score: float,
        *,
        bm25_hits: list[tuple[str, float]],
        vector_hits: list[tuple[str, float]],
        matched_entity_ids: set[str],
    ) -> tuple[float, dict[str, object]]:
        component_scores: dict[str, float] = {"fusion": fusion_score}
        sources: list[str] = []
        bm25_lookup = dict(bm25_hits)
        vector_lookup = dict(vector_hits)
        if unit.ku_id in bm25_lookup:
            sources.append("bm25")
            component_scores["bm25_rank_score"] = 0.0 - bm25_lookup[unit.ku_id]
        if unit.ku_id in vector_lookup:
            sources.append("vector")
            component_scores["vector_similarity"] = vector_lookup[unit.ku_id]

        final_score = fusion_score
        unit_entity_ids = {
            entity.entity_id for entity in unit.entities if entity.entity_id
        }
        if matched_entity_ids and unit_entity_ids & matched_entity_ids:
            component_scores["entity_bonus"] = 0.2
            final_score += 0.2
        if query.filters.event_types and unit.unit_type in query.filters.event_types:
            component_scores["event_type_bonus"] = 0.1
            final_score += 0.1
        recency_bonus = self._unit_anchor(unit).timestamp() / 10_000_000_000_000
        component_scores["recency_bonus"] = recency_bonus
        final_score += recency_bonus
        metadata = {
            "score": final_score,
            "sources": sources,
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

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            raise RuntimeError("cannot compute cosine similarity with zero-length embedding")
        return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
