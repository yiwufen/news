"""
Search index builders for normalized knowledge units.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge_base import KnowledgeUnit, KnowledgeUnitRepository
    from src.retrieval.vector_index import VectorIndex

logger = logging.getLogger(__name__)


class KnowledgeIndexBuilder:
    """Build and rebuild KnowledgeUnit FTS + vector retrieval indexes.

    FTS rows are incrementally synced during ``save_batch()``, so
    ``build_for_units`` only handles vector indexing when a VectorIndex
    is provided.
    """

    def __init__(
        self,
        knowledge_units: KnowledgeUnitRepository,
        vector_index: VectorIndex | None = None,
    ) -> None:
        self.knowledge_units = knowledge_units
        self._vector_index = vector_index

    def build_for_units(self, units: list[KnowledgeUnit]) -> int:
        """Incremental vector indexing for newly saved KUs.

        Returns the number of new embeddings created.
        """
        if self._vector_index is None:
            return 0
        try:
            count = self._vector_index.index_units(units)
            if count > 0:
                logger.info("Stage 5: embedded %d knowledge units", count)
            return count
        except Exception:
            logger.warning("Vector indexing failed (non-blocking)", exc_info=True)
            return 0

    def rebuild_all(self) -> int:
        """Rebuild FTS index from all persisted KnowledgeUnit rows."""
        return self.knowledge_units.rebuild_fts_index()

    def build_vectors(self, vector_index: VectorIndex) -> int:
        """Build vector index for all KUs not yet embedded."""
        units = self.knowledge_units.get_all()
        return vector_index.index_units(units)

    def rebuild_vectors(self, vector_index: VectorIndex) -> int:
        """Full rebuild: clear existing vectors and re-embed all KUs."""
        units = self.knowledge_units.get_all()
        return vector_index.rebuild(units)


def rebuild_knowledge_indexes(
    db_path: str = "data/news.db",
) -> int:
    """Rebuild FTS indexes from persisted KnowledgeUnit rows."""
    from src.knowledge_base import KnowledgeUnitRepository

    return KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
    ).rebuild_all()


def build_vector_index(
    db_path: str = "data/news.db",
) -> int:
    """Build vector index for all KUs. Returns count of new embeddings."""
    from src.knowledge_base import KnowledgeUnitRepository
    from src.retrieval.embedding import OpenAICompatEmbedding
    from src.retrieval.vector_index import VectorIndex

    provider = OpenAICompatEmbedding()
    vector_index = VectorIndex(db_path, provider)
    builder = KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
    )
    return builder.build_vectors(vector_index)


def rebuild_vector_index(
    db_path: str = "data/news.db",
) -> int:
    """Full rebuild of vector index. Returns total count."""
    from src.knowledge_base import KnowledgeUnitRepository
    from src.retrieval.embedding import OpenAICompatEmbedding
    from src.retrieval.vector_index import VectorIndex

    provider = OpenAICompatEmbedding()
    vector_index = VectorIndex(db_path, provider)
    builder = KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
    )
    return builder.rebuild_vectors(vector_index)


def try_create_vector_index(db_path: str = "data/news.db") -> "VectorIndex | None":
    """Attempt to create a VectorIndex if embedding is configured.

    Returns None (graceful degradation) if credentials are missing.
    """
    try:
        from src.retrieval.embedding import OpenAICompatEmbedding
        from src.retrieval.vector_index import VectorIndex

        provider = OpenAICompatEmbedding()
        return VectorIndex(db_path, provider)
    except Exception:
        logger.info("Vector indexing disabled (no embedding config)")
        return None
