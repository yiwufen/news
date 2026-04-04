"""
Search index builders for normalized knowledge units.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping, Sequence

from src.entities import EntityRepository
from src.knowledge_base import (
    KnowledgeUnit,
    KnowledgeUnitEmbedding,
    KnowledgeUnitRepository,
    build_knowledge_unit_search_text,
)
from src.retrieval.embedding_client import EmbeddingClient, OpenAIEmbeddingClient


class KnowledgeIndexBuilder:
    """Build and rebuild KnowledgeUnit retrieval indexes."""

    def __init__(
        self,
        knowledge_units: KnowledgeUnitRepository,
        entities: EntityRepository,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.knowledge_units = knowledge_units
        self.entities = entities
        self.embedding_client = embedding_client or OpenAIEmbeddingClient()

    def build_for_units(self, units: Sequence[KnowledgeUnit]) -> int:
        if not units:
            return 0
        entity_ids = {
            entity.entity_id
            for unit in units
            for entity in unit.entities
            if entity.entity_id
        }
        entity_map = {
            entity.entity_id: entity
            for entity in self.entities.get_by_ids(entity_ids)
        }
        texts = [
            build_knowledge_unit_search_text(
                unit,
                entity_names=self._entity_names_for_unit(unit, entity_map),
            )
            for unit in units
        ]
        embeddings = self.embedding_client.embed_texts(texts)
        if len(embeddings) != len(units):
            raise RuntimeError("embedding client returned mismatched embedding count")
        now = datetime.now(UTC)
        model_name = getattr(self.embedding_client, "model", "unknown")
        entries: list[KnowledgeUnitEmbedding] = []
        expected_dim: int | None = None
        for unit, embedding in zip(units, embeddings, strict=True):
            if not embedding:
                raise RuntimeError(f"embedding client returned an empty embedding for {unit.ku_id}")
            if expected_dim is None:
                expected_dim = len(embedding)
            elif len(embedding) != expected_dim:
                raise RuntimeError("embedding client returned inconsistent embedding dimensions")
            entries.append(
                KnowledgeUnitEmbedding(
                    ku_id=unit.ku_id,
                    embedding_model=model_name,
                    embedding_dim=len(embedding),
                    embedding=embedding,
                    updated_at=now,
                )
            )
        return self.knowledge_units.save_embeddings(entries)

    def rebuild_all(self) -> int:
        self.knowledge_units.rebuild_fts_index()
        units = self.knowledge_units.get_all()
        return self.build_for_units(units)

    def _entity_names_for_unit(self, unit: KnowledgeUnit, entity_map: Mapping[str, object]) -> list[str]:
        names: list[str] = []
        for entity_ref in unit.entities:
            names.append(entity_ref.mention)
            if not entity_ref.entity_id:
                continue
            entity = entity_map.get(entity_ref.entity_id)
            if entity is None:
                continue
            canonical_name = getattr(entity, "canonical_name", None)
            aliases = getattr(entity, "aliases", [])
            if canonical_name:
                names.append(canonical_name)
            names.extend(alias for alias in aliases if alias)
        return names


def rebuild_knowledge_indexes(
    db_path: str = "data/news.db",
    embedding_client: EmbeddingClient | None = None,
) -> int:
    """Rebuild FTS and embedding indexes from persisted KnowledgeUnit rows."""
    builder = KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
        entities=EntityRepository(db_path),
        embedding_client=embedding_client,
    )
    return builder.rebuild_all()
