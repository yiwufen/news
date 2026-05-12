"""LanceDB-backed vector index for KnowledgeUnit dense retrieval."""

from __future__ import annotations

import logging
from pathlib import Path

import lancedb
import pyarrow as pa

from src.knowledge_base import KnowledgeUnit
from src.retrieval.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

_TABLE_NAME = "knowledge_units"


def build_embedding_text(unit: KnowledgeUnit) -> str:
    """Build semantically rich text for embedding a KnowledgeUnit."""
    parts = [unit.summary]

    entity_mentions = [e.mention for e in unit.entities if e.mention]
    if entity_mentions:
        parts.append("[实体] " + " ".join(entity_mentions))

    if unit.unit_type:
        parts.append("[类型] " + unit.unit_type)

    if unit.tags:
        parts.append("[标签] " + " ".join(unit.tags))

    return " ".join(parts)


class VectorIndex:
    """Vector index backed by LanceDB.

    Embedded mode — no server required. Stores embeddings with metadata
    and supports cosine similarity search with optional filters.
    """

    def __init__(self, db_path: str, provider: EmbeddingProvider) -> None:
        # db_path is the SQLite path; vector DB lives alongside it
        vec_dir = str(Path(db_path).parent / "vector_db")
        self._db = lancedb.connect(vec_dir)
        self._provider = provider
        self._dim: int | None = None

    def _table_names(self) -> list[str]:
        return self._db.list_tables().tables  # type: ignore[no-any-return]

    def _ensure_table(self, dim: int) -> lancedb.table.Table:
        """Get or create the LanceDB table."""
        self._dim = dim
        if _TABLE_NAME in self._table_names():
            return self._db.open_table(_TABLE_NAME)
        # Create with empty schema — first batch will define columns
        schema = pa.schema([
            pa.field("ku_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("model_name", pa.string()),
            pa.field("source_text", pa.string()),
        ])
        return self._db.create_table(_TABLE_NAME, schema=schema)

    def index_units(self, units: list[KnowledgeUnit], *, batch_size: int = 20) -> int:
        """Embed and store vectors for KUs not yet indexed. Returns count."""
        if not units:
            return 0

        existing_ids: set[str] = set()
        if _TABLE_NAME in self._table_names():
            table = self._db.open_table(_TABLE_NAME)
            arrow_table = table.to_arrow()
            for ku_id in arrow_table.column("ku_id").to_pylist():
                existing_ids.add(ku_id)

        new_units = [u for u in units if u.ku_id not in existing_ids]
        if not new_units:
            return 0

        total_indexed = 0
        for i in range(0, len(new_units), batch_size):
            batch = new_units[i : i + batch_size]
            texts = [build_embedding_text(u) for u in batch]
            vectors = self._provider.embed(texts)
            dim = len(vectors[0])

            table = self._ensure_table(dim)

            records = [
                {
                    "ku_id": unit.ku_id,
                    "vector": vector,
                    "model_name": self._provider.model_name,
                    "source_text": text,
                }
                for unit, vector, text in zip(batch, vectors, texts)
            ]
            table.add(records)
            total_indexed += len(batch)
            logger.info("Indexed %d/%d vectors", total_indexed, len(new_units))

        return total_indexed

    def search(
        self, query_text: str, *, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Cosine similarity search. Returns (ku_id, similarity) sorted desc."""
        if _TABLE_NAME not in self._table_names():
            return []

        query_vectors = self._provider.embed([query_text])
        if not query_vectors:
            return []

        table = self._db.open_table(_TABLE_NAME)
        query = table.search(query_vectors[0])
        results = (
            query.metric("cosine")  # type: ignore[union-attr]
            .limit(top_k)
            .select(["ku_id"])
            .to_list()
        )

        # LanceDB cosine distance: 0 = identical, 2 = opposite
        return [
            (str(row["ku_id"]), 1.0 - float(row["_distance"]))
            for row in results
        ]

    def is_available(self) -> bool:
        if _TABLE_NAME not in self._table_names():
            return False
        table = self._db.open_table(_TABLE_NAME)
        return table.count_rows() > 0

    def indexed_count(self) -> int:
        if _TABLE_NAME not in self._table_names():
            return 0
        table = self._db.open_table(_TABLE_NAME)
        return table.count_rows()

    def rebuild(self, units: list[KnowledgeUnit]) -> int:
        """Full rebuild: drop and re-index all."""
        if _TABLE_NAME in self._table_names():
            self._db.drop_table(_TABLE_NAME)
        return self.index_units(units)
