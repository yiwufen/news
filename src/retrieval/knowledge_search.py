"""
Knowledge-centric multi-path retrieval over KnowledgeUnit, Entity, and EventCluster.

Retrieval paths:
  Path A: Entity-ID Lookup — direct query by entity_ids JSON column (primary for entity queries)
  Path B: Dense Retrieval — embedding-based semantic search (primary for Chinese/topic queries)
  Path C: BM25/FTS5 fallback — text search when entity resolution fails
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from src.entities import (
    Entity,
    EntityRepository,
    EntityResolver,
    build_entity_name_variants,
)
from src.event_clustering import EventCluster, EventClusterRepository, EventClusterer
from src.schemas.query import IntentType, StructuredQuery
from src.knowledge_base import (
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    adapt_article_to_raw_document,
    build_knowledge_unit_search_text,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.retrieval.scoring import INTENT_PROFILES, ScoringProfile
from src.retrieval.vector_index import VectorIndex

logger = logging.getLogger(__name__)


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
    retrieval_path: str = "bm25"

    def to_dict(self) -> dict[str, object]:
        return {
            "knowledge_units": [unit.model_dump(mode="json") for unit in self.knowledge_units],
            "entities": [entity.model_dump(mode="json") for entity in self.entities],
            "event_clusters": [cluster.model_dump(mode="json") for cluster in self.event_clusters],
            "total_count": self.total_count,
            "retrieval": {
                "retrieval_mode": self.retrieval_path,
                "bm25_count": self.bm25_count,
                "applied_filters": self.applied_filters,
                "hit_scores": self.hit_scores,
            },
        }


class KnowledgeSearcher:
    """Search the normalized knowledge store via multi-path retrieval."""

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
        # Dense retrieval (optional — graceful degradation)
        self._vector_index: VectorIndex | None = None
        try:
            from src.retrieval.embedding import OpenAICompatEmbedding
            from src.retrieval.vector_index import VectorIndex as _VI

            provider = OpenAICompatEmbedding()
            idx = _VI(db_path, provider)
            if idx.is_available():
                self._vector_index = idx
                logger.info("Dense retrieval enabled (%d vectors)", idx.indexed_count())
            else:
                logger.info(
                    "Vector index empty — run 'knowledge-cli index-vectors' to build"
                )
        except Exception:
            logger.info("Dense retrieval unavailable (no embedding config or empty index)")

    # ------------------------------------------------------------------
    # Main entry point: intent-dispatched search
    # ------------------------------------------------------------------

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        query = request.structured_query
        strategy = {
            IntentType.COMPARATIVE_ANALYSIS: self._search_comparative,
            IntentType.TOPIC_RESEARCH: self._search_topic,
            IntentType.ENTITY_TIMELINE: self._search_timeline,
        }.get(query.intent)
        if strategy:
            return strategy(request)
        return self._search_with_relaxation(request)

    # ------------------------------------------------------------------
    # Default search with relaxation cascade
    # ------------------------------------------------------------------

    def _search_with_relaxation(
        self, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResult:
        """Search with relaxation: entity-id → dense → BM25, merged and re-ranked."""
        query = request.structured_query
        profile = INTENT_PROFILES.get(query.intent)
        matched_entities = self.entities.find_by_names(query.entities)
        entity_ids = [e.entity_id for e in matched_entities]
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)
        candidate_limit = max(request.top_k * 5, request.top_k)

        # Path A: Entity-ID lookup
        bm25_hits: list[tuple[str, float]] = []
        if entity_ids:
            ku_ids = self.units.find_by_entity_ids(
                entity_ids,
                time_range=time_range,
                event_types=event_types,
                limit=candidate_limit,
            )
            bm25_hits = [(kid, -1.0) for kid in ku_ids]

        # Path C: BM25 fallback (if entity-id found nothing or no entity match)
        if not bm25_hits:
            bm25_hits = self._bm25_search(query, matched_entities)

        # Path B: Dense retrieval — runs as fallback when BM25 is empty,
        # and as supplement when BM25 has results.
        dense_scores: dict[str, float] = self._dense_search(query)

        # Merge: add dense-only candidates to the pool
        existing_ids = {kid for kid, _ in bm25_hits}
        for kid in dense_scores:
            if kid not in existing_ids:
                bm25_hits.append((kid, 0.0))

        if not bm25_hits and not dense_scores:
            # Pure time-range fallback: no entities, no search terms,
            # but user specified a time range — return recent KUs.
            if time_range:
                time_ku_ids = self.units.find_by_time_range(
                    time_range, limit=candidate_limit
                )
                if time_ku_ids:
                    bm25_hits = [(kid, 0.0) for kid in time_ku_ids]

        if not bm25_hits and not dense_scores:
            result = self._empty_result(request, matched_entities)
            result.retrieval_path = "no_results"
            return result

        result = self._build_ranked_result(
            request=request,
            bm25_hits=bm25_hits,
            matched_entities=matched_entities,
            dense_scores=dense_scores,
            profile=profile,
        )

        # Label retrieval path
        if entity_ids and dense_scores:
            result.retrieval_path = "entity_id+dense"
        elif entity_ids:
            result.retrieval_path = "entity_id_lookup"
        elif dense_scores:
            result.retrieval_path = "dense"
        elif time_range and not query.original_query.strip() and not query.entities:
            result.retrieval_path = "time_range"
        else:
            result.retrieval_path = "bm25_fallback"
        return result

    # ------------------------------------------------------------------
    # Dense retrieval helper
    # ------------------------------------------------------------------

    def _dense_search(self, query: StructuredQuery) -> dict[str, float]:
        """Run dense retrieval if available. Returns ku_id → cosine_similarity."""
        if self._vector_index is None:
            return {}
        try:
            query_text = query.original_query or " ".join(query.entities)
            if not query_text.strip():
                return {}
            hits = self._vector_index.search(query_text, top_k=60)
            return {kid: sim for kid, sim in hits}
        except Exception:
            logger.warning("Dense retrieval failed", exc_info=True)
            return {}

    def _bm25_search(
        self,
        query: StructuredQuery,
        matched_entities: list[Entity],
    ) -> list[tuple[str, float]]:
        """BM25 text search with two-stage broadening."""
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)
        candidate_limit = 60

        entity_id_filter = [e.entity_id for e in matched_entities] or None
        fts_query = self._build_fts_query(query, matched_entities)
        if fts_query.strip():
            hits = self.units.search_bm25(
                fts_query,
                top_k=candidate_limit,
                time_range=time_range,
                event_types=event_types,
                entity_ids=entity_id_filter,
            )
            if hits:
                return hits

        broad_query = self._build_text_only_fts_query(query)
        if broad_query.strip():
            return self.units.search_bm25(
                broad_query,
                top_k=candidate_limit,
                time_range=time_range,
                event_types=event_types,
            )
        return []

    # ------------------------------------------------------------------
    # Path A: Entity-ID Lookup (primary for entity-centric queries)
    # ------------------------------------------------------------------

    def _search_by_entity_ids(
        self,
        request: KnowledgeSearchRequest,
        matched_entities: list[Entity],
        entity_ids: list[str],
    ) -> KnowledgeSearchResult:
        query = request.structured_query
        profile = INTENT_PROFILES.get(query.intent)
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)
        candidate_limit = max(request.top_k * 5, request.top_k)

        ku_ids = self.units.find_by_entity_ids(
            entity_ids,
            time_range=time_range,
            event_types=event_types,
            limit=candidate_limit,
        )

        if not ku_ids:
            # Entity resolved but no KUs — fallback to BM25
            return self._search_bm25_fallback(request, matched_entities)

        hits: list[tuple[str, float]] = [(ku_id, -1.0) for ku_id in ku_ids]
        result = self._build_ranked_result(
            request=request,
            bm25_hits=hits,
            matched_entities=matched_entities,
            profile=profile,
        )
        result.retrieval_path = "entity_id_lookup"
        return result

    # ------------------------------------------------------------------
    # Path C: BM25 fallback (when entity resolution fails)
    # ------------------------------------------------------------------

    def _search_bm25_fallback(
        self,
        request: KnowledgeSearchRequest,
        matched_entities: list[Entity],
    ) -> KnowledgeSearchResult:
        """BM25 text search — used when entity resolution produces no matches."""
        query = request.structured_query
        profile = INTENT_PROFILES.get(query.intent)
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)
        candidate_limit = max(request.top_k * 3, request.top_k)

        # Use entity names + original query terms for FTS
        entity_id_filter = [e.entity_id for e in matched_entities] or None
        fts_query = self._build_fts_query(query, matched_entities)
        if not fts_query.strip():
            return self._empty_result(request, matched_entities)

        bm25_hits = self.units.search_bm25(
            fts_query,
            top_k=candidate_limit,
            time_range=time_range,
            event_types=event_types,
            entity_ids=entity_id_filter,
        )

        if not bm25_hits:
            # Try broader BM25 with just original query terms (no entity names)
            broad_query = self._build_text_only_fts_query(query)
            if broad_query.strip():
                bm25_hits = self.units.search_bm25(
                    broad_query,
                    top_k=candidate_limit,
                    time_range=time_range,
                    event_types=event_types,
                )

        # Dense fallback when BM25 finds nothing
        dense_scores: dict[str, float] = {}
        if not bm25_hits:
            dense_scores = self._dense_search(query)
            for kid in dense_scores:
                bm25_hits.append((kid, 0.0))

        result = self._build_ranked_result(
            request=request,
            bm25_hits=bm25_hits,
            matched_entities=matched_entities,
            dense_scores=dense_scores,
            profile=profile,
        )
        result.retrieval_path = "dense_fallback" if dense_scores and not entity_id_filter else "bm25_fallback"
        return result

    # ------------------------------------------------------------------
    # Intent-specific strategies
    # ------------------------------------------------------------------

    def _search_comparative(
        self, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResult:
        """Balanced retrieval for A vs B comparison.

        Strategy: per-entity recall → union of candidates → coverage-aware rerank.
        KUs that mention multiple entities get a co-occurrence bonus.
        """
        query = request.structured_query
        if len(query.entities) < 2:
            return self._search_with_relaxation(request)

        profile = INTENT_PROFILES.get(query.intent)
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)

        # Per-entity recall — track which entities each KU mentions
        coverage: dict[str, set[int]] = {}  # ku_id -> entity indices
        bm25_scores: dict[str, float] = {}  # ku_id -> best (most-negative) bm25
        all_matched: list[Entity] = []

        for idx, entity_name in enumerate(query.entities):
            matched = self.entities.find_by_names([entity_name])
            all_matched.extend(matched)
            eids = [e.entity_id for e in matched]
            if eids:
                # Entity resolved: use entity-id lookup (no bm25 score, use -1.0)
                ku_ids = self.units.find_by_entity_ids(
                    eids,
                    time_range=time_range,
                    event_types=event_types,
                    limit=request.top_k * 3,
                )
                hits = [(kid, -1.0) for kid in ku_ids]
            else:
                # Entity not resolved: BM25 fallback with broader query
                fts = self._build_fts_query_for_terms([entity_name, query.original_query])
                hits = self.units.search_bm25(
                    fts, top_k=request.top_k * 3,
                    time_range=time_range,
                    event_types=event_types,
                ) if fts.strip() else []

            for kid, score in hits:
                coverage.setdefault(kid, set()).add(idx)
                # Keep most informative (lowest, most-negative) bm25 across entities
                bm25_scores[kid] = min(bm25_scores.get(kid, 0.0), score)

        if not coverage:
            # No candidates at all — fall back to standard path
            return self._search_with_relaxation(request)

        # Build hits list with coverage-aware scoring
        hits = [(kid, bm25_scores[kid]) for kid in coverage]
        result = self._build_ranked_result_comparative(
            request=request,
            bm25_hits=hits,
            coverage=coverage,
            matched_entities=all_matched,
            profile=profile,
        )
        result.retrieval_path = "comparative"
        return result

    def _search_topic(
        self, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResult:
        """Topic search — entity lookup first, BM25 fallback for unknown topics."""
        query = request.structured_query
        matched_entities = self.entities.find_by_names(query.entities)
        entity_ids = [e.entity_id for e in matched_entities]

        if entity_ids:
            # Topic is a known entity — use entity-id lookup
            return self._search_by_entity_ids(request, matched_entities, entity_ids)

        # Topic not in entity DB — BM25 text search with original terms
        return self._search_bm25_fallback(request, matched_entities)

    def _search_timeline(
        self, request: KnowledgeSearchRequest
    ) -> KnowledgeSearchResult:
        """Timeline search — temporal bucketing for even coverage."""
        query = request.structured_query
        profile = INTENT_PROFILES.get(query.intent)
        matched_entities = self.entities.find_by_names(query.entities)
        entity_ids = [e.entity_id for e in matched_entities]
        time_range = self._serialize_time_range(query)
        event_types = self._expand_event_types(query)

        if not entity_ids:
            return self._search_bm25_fallback(request, matched_entities)

        # Get all candidates with amplified limit
        ku_ids = self.units.find_by_entity_ids(
            entity_ids,
            time_range=time_range,
            event_types=event_types,
            limit=max(request.top_k * 5, 100),
        )

        if not ku_ids:
            return self._search_bm25_fallback(request, matched_entities)

        # Bucket by month for temporal coverage
        units = self.units.get_by_ids(ku_ids)
        buckets: dict[str, list[KnowledgeUnit]] = defaultdict(list)
        for unit in units:
            anchor = self._unit_anchor(unit)
            month_key = anchor.strftime("%Y-%m")
            buckets[month_key].append(unit)

        # Select top N per bucket, sorted by recency within bucket
        per_bucket = max(request.top_k // max(len(buckets), 1), 2)
        selected_units: list[KnowledgeUnit] = []
        for month_key in sorted(buckets.keys(), reverse=True):
            bucket_units = buckets[month_key]
            bucket_units.sort(key=lambda u: self._unit_anchor(u), reverse=True)
            selected_units.extend(bucket_units[:per_bucket])

        selected_units.sort(key=lambda u: self._unit_anchor(u), reverse=True)
        selected_units = selected_units[:request.top_k]

        # Build result using entity scoring
        matched_entity_ids = {e.entity_id for e in matched_entities}
        hit_scores: dict[str, dict[str, object]] = {}
        for unit in selected_units:
            score, meta = self._score_final_hit(
                unit, query, -1.0,
                matched_entity_ids=matched_entity_ids,
                dense_score=0.0,
                profile=profile,
            )
            hit_scores[unit.ku_id] = meta

        selected_entity_ids = {
            entity.entity_id
            for unit in selected_units
            for entity in unit.entities
            if entity.entity_id
        } | matched_entity_ids
        selected_cluster_ids = {
            unit.cluster_id for unit in selected_units if unit.cluster_id
        }

        result_entities = self.entities.get_by_ids(selected_entity_ids)
        cluster_lookup_ids = matched_entity_ids if matched_entity_ids else selected_entity_ids
        related_clusters = self.clusters.find_related(
            primary_entity_ids=cluster_lookup_ids,
            cluster_types=query.filters.event_types,
            time_range=time_range,
        )
        related_cluster_ids = {c.cluster_id for c in related_clusters}
        result_clusters = self.clusters.get_by_ids(
            list(selected_cluster_ids | related_cluster_ids)
        )

        return KnowledgeSearchResult(
            knowledge_units=selected_units,
            entities=result_entities,
            event_clusters=result_clusters,
            total_count=len(units),
            bm25_count=len(units),
            applied_filters=self._build_applied_filters(query, matched_entities),
            hit_scores=hit_scores,
            retrieval_path="timeline",
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
        dense_scores: dict[str, float] | None = None,
        profile: ScoringProfile | None = None,
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
        dense = dense_scores or {}

        for ku_id in candidate_ids:
            unit = unit_map.get(ku_id)
            if unit is None:
                continue
            final_score, metadata = self._score_final_hit(
                unit,
                request.structured_query,
                bm25_lookup.get(ku_id, 0.0),
                matched_entity_ids=matched_entity_ids,
                dense_score=dense.get(ku_id, 0.0),
                profile=profile,
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
        # Only use query-matched entities for cluster lookup to avoid
        # over-expansion from tangential entities in top KUs.
        cluster_lookup_ids = matched_entity_ids if matched_entity_ids else selected_entity_ids
        related_clusters = self.clusters.find_related(
            primary_entity_ids=cluster_lookup_ids,
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

    def _build_ranked_result_comparative(
        self,
        *,
        request: KnowledgeSearchRequest,
        bm25_hits: list[tuple[str, float]],
        coverage: dict[str, set[int]],
        matched_entities: list[Entity],
        dense_scores: dict[str, float] | None = None,
        profile: ScoringProfile | None = None,
    ) -> KnowledgeSearchResult:
        """Build ranked result for COMPARATIVE_ANALYSIS with coverage bonus.

        KUs that mention multiple query entities get a co-occurrence bonus:
        - 2 entities covered: +3.0
        - 3 entities covered: +6.0
        - etc.
        """
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

        matched_entity_ids = {entity.entity_id for entity in matched_entities}
        dense = dense_scores or {}

        for ku_id in candidate_ids:
            unit = unit_map.get(ku_id)
            if unit is None:
                continue
            final_score, metadata = self._score_final_hit(
                unit,
                request.structured_query,
                bm25_lookup.get(ku_id, 0.0),
                matched_entity_ids=matched_entity_ids,
                dense_score=dense.get(ku_id, 0.0),
                profile=profile,
            )

            # Add coverage bonus for KUs mentioning multiple query entities
            covered = len(coverage.get(ku_id, set()))
            if covered > 1:
                coverage_bonus = 3.0 * (covered - 1)
                final_score += coverage_bonus
                component_scores = metadata.get("component_scores", {})
                if isinstance(component_scores, dict):
                    component_scores["coverage_bonus"] = coverage_bonus  # type: ignore[index]
                metadata["coverage"] = covered  # type: ignore[index]

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
        cluster_lookup_ids = matched_entity_ids if matched_entity_ids else selected_entity_ids
        related_clusters = self.clusters.find_related(
            primary_entity_ids=cluster_lookup_ids,
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

    def _build_text_only_fts_query(self, query: StructuredQuery) -> str:
        """FTS query using only original query terms (no entity names)."""
        terms: list[str] = []
        for token in self._tokenize_query(query.original_query.lower()):
            terms.append(token)
        for entity_name in query.entities:
            terms.extend(self._tokenize_query(entity_name.lower()))
            if entity_name.strip():
                terms.append(self._quote_fts_phrase(entity_name.strip()))
        for event_type in query.filters.event_types or []:
            terms.extend(self._tokenize_query(event_type.lower()))
        unique_terms = list(dict.fromkeys(term for term in terms if term))
        return " OR ".join(unique_terms)

    def _build_fts_query_for_terms(self, terms: list[str]) -> str:
        """Build FTS query from raw term strings."""
        parts: list[str] = []
        for term in terms:
            tokens = self._tokenize_query(term.lower())
            parts.extend(tokens)
            # Only add phrase quotes for non-Chinese terms (FTS5 unicode61 doesn't handle CJK phrases well)
            if term.strip() and not re.search(r"[一-鿿]", term.strip()):
                parts.append(self._quote_fts_phrase(term.strip()))
        unique = list(dict.fromkeys(p for p in parts if p))
        return " OR ".join(unique)

    def _expand_event_types(self, query: StructuredQuery) -> list[str] | None:
        event_types = query.filters.event_types or None
        if event_types:
            from src.retrieval.event_type_mapping import expand_event_types
            event_types = expand_event_types(event_types)
        return event_types

    def _score_final_hit(
        self,
        unit: KnowledgeUnit,
        query: StructuredQuery,
        bm25_score: float,
        *,
        matched_entity_ids: set[str],
        dense_score: float = 0.0,
        profile: ScoringProfile | None = None,
    ) -> tuple[float, dict[str, object]]:
        from src.retrieval.scoring import RISK_UNIT_TYPES

        p = profile or ScoringProfile()
        component_scores: dict[str, float] = {
            "bm25_score": bm25_score,
            "dense_score": dense_score,
        }
        final_score = 0.0

        # Entity-ID match (highest priority)
        unit_entity_ids = {
            entity.entity_id for entity in unit.entities if entity.entity_id
        }
        if matched_entity_ids and unit_entity_ids & matched_entity_ids:
            component_scores["entity_bonus"] = p.entity_bonus
            final_score += p.entity_bonus

        # Dense semantic score
        if dense_score > 0:
            weighted = dense_score * p.dense_weight
            component_scores["dense_weighted"] = weighted
            final_score += weighted

        # Event type match
        if query.filters.event_types and unit.unit_type in query.filters.event_types:
            component_scores["event_type_bonus"] = p.event_type_bonus
            final_score += p.event_type_bonus

        # BM25 text score (normalize negative to positive)
        if bm25_score < 0:
            bm25_pos = min(-bm25_score * p.bm25_weight, p.bm25_cap)
            component_scores["bm25_weighted"] = bm25_pos
            final_score += bm25_pos

        recency_bonus = (
            self._unit_anchor(unit).timestamp() / 10_000_000_000_000
        ) * p.recency_scale
        component_scores["recency_bonus"] = recency_bonus
        final_score += recency_bonus

        # Risk-type boost (RISK_ASSESSMENT intent)
        if p.risk_type_bonus > 0 and unit.unit_type in RISK_UNIT_TYPES:
            component_scores["risk_type_bonus"] = p.risk_type_bonus
            final_score += p.risk_type_bonus

        # Causal-chain boost (EVENT_IMPACT_ANALYSIS intent)
        if p.causal_chain_bonus > 0 and unit.relation_hints:
            component_scores["causal_chain_bonus"] = p.causal_chain_bonus
            final_score += p.causal_chain_bonus

        # Recency boost for recent events
        if p.recency_boost_days > 0:
            from datetime import UTC, datetime

            anchor = self._unit_anchor(unit)
            days_ago = (datetime.now(UTC) - anchor).days
            if 0 <= days_ago <= p.recency_boost_days:
                boost = (p.recency_boost_days - days_ago) / p.recency_boost_days * 2.0
                component_scores["recency_boost"] = boost
                final_score += boost

        metadata = {
            "score": final_score,
            "sources": ["dense" if dense_score > 0 else "bm25"],
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
        from src.chinese_text import segment_query

        return segment_query(raw_query)

    def _quote_fts_phrase(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _unit_anchor(self, unit: KnowledgeUnit) -> datetime:
        return unit.time.event_time or unit.time.published_at
