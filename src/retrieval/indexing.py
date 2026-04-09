"""
Search index builders for normalized knowledge units.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.knowledge_base import KnowledgeUnitRepository


class KnowledgeIndexBuilder:
    """Build and rebuild KnowledgeUnit FTS retrieval indexes.

    Note: FTS rows are incrementally synced during ``save_batch()``, so
    ``build_for_units`` is effectively a no-op.  ``rebuild_all`` exists for
    explicit full-rebuild scenarios (e.g. backfill after schema changes).
    """

    def __init__(self, knowledge_units: KnowledgeUnitRepository) -> None:
        self.knowledge_units = knowledge_units

    def build_for_units(self, units: object) -> int:
        """No-op: FTS rows are already synced by ``save_batch``."""
        return 0

    def rebuild_all(self) -> int:
        """Rebuild FTS index from all persisted KnowledgeUnit rows."""
        return self.knowledge_units.rebuild_fts_index()


def rebuild_knowledge_indexes(
    db_path: str = "data/news.db",
) -> int:
    """Rebuild FTS indexes from persisted KnowledgeUnit rows."""
    from src.knowledge_base import KnowledgeUnitRepository

    return KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
    ).rebuild_all()
