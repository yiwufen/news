"""FAISS-backed vector index for KnowledgeUnit dense retrieval."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import faiss
import numpy as np

from src.knowledge_base import KnowledgeUnit
from src.retrieval.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

_INDEX_FILE = "faiss.index"
_ID_MAP_FILE = "id_map.json"


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
    """Vector index backed by FAISS (IndexFlatIP with L2-normalized vectors).

    Cosine similarity via inner product on unit vectors.  No server required.
    Index and ID map are persisted to disk after each write operation.
    """

    def __init__(self, db_path: str, provider: EmbeddingProvider) -> None:
        self._vec_dir = Path(db_path).parent / "vector_db"
        self._provider = provider
        self._dim: int | None = None

        # State loaded lazily
        self._index: faiss.Index | None = None
        self._id_map: dict[int, str] = {}  # int64 → ku_id
        self._reverse_map: dict[str, int] = {}  # ku_id → int64
        self._next_id: int = 0

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self._vec_dir / _INDEX_FILE

    def _id_map_path(self) -> Path:
        return self._vec_dir / _ID_MAP_FILE

    def _load(self) -> None:
        """Load existing index and ID map from disk (if present)."""
        if self._index is not None:
            return

        if self._index_path().exists():
            idx = faiss.read_index(str(self._index_path()))
            assert idx is not None
            self._index = idx
            self._dim = idx.d
            logger.info("Loaded FAISS index (%d vectors)", idx.ntotal)
        else:
            self._index = None
            self._dim = None

        if self._id_map_path().exists():
            raw: dict[str, str] = json.loads(self._id_map_path().read_text(encoding="utf-8"))
            self._id_map = {int(k): v for k, v in raw.items()}
            self._reverse_map = {v: k for k, v in self._id_map.items()}
            self._next_id = max(self._id_map.keys(), default=-1) + 1
        else:
            self._id_map = {}
            self._reverse_map = {}
            self._next_id = 0

    def _save(self) -> None:
        """Persist current index and ID map to disk."""
        if self._index is None:
            return
        self._vec_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path()))
        raw = {str(k): v for k, v in self._id_map.items()}
        self._id_map_path().write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    def _create_index(self, dim: int) -> faiss.Index:
        """Create a new FAISS IndexIDMap wrapping IndexFlatIP."""
        flat = faiss.IndexFlatIP(dim)
        return faiss.IndexIDMap(flat)

    # ------------------------------------------------------------------
    # Public interface (unchanged from LanceDB version)
    # ------------------------------------------------------------------

    def index_units(self, units: list[KnowledgeUnit], *, batch_size: int = 20) -> int:
        """Embed and store vectors for KUs not yet indexed. Returns count."""
        if not units:
            return 0

        self._load()

        new_units = [u for u in units if u.ku_id not in self._reverse_map]
        if not new_units:
            return 0

        total_indexed = 0
        for i in range(0, len(new_units), batch_size):
            batch = new_units[i : i + batch_size]
            texts = [build_embedding_text(u) for u in batch]
            vectors = self._provider.embed(texts)
            dim = len(vectors[0])

            if self._index is None:
                self._dim = dim
                self._index = self._create_index(dim)

            arr = np.array(vectors, dtype=np.float32)
            faiss.normalize_L2(arr)

            ids = np.array(
                [self._next_id + j for j in range(len(batch))],
                dtype=np.int64,
            )
            assert self._index is not None
            self._index.add_with_ids(arr, ids)  # type: ignore[call-arg]

            for j, unit in enumerate(batch):
                int_id = int(ids[j])
                self._id_map[int_id] = unit.ku_id
                self._reverse_map[unit.ku_id] = int_id
            self._next_id += len(batch)

            total_indexed += len(batch)
            logger.info("Indexed %d/%d vectors", total_indexed, len(new_units))

        self._save()
        return total_indexed

    def search(self, query_text: str, *, top_k: int = 20) -> list[tuple[str, float]]:
        """Cosine similarity search. Returns (ku_id, similarity) sorted desc."""
        self._load()
        if self._index is None or self._index.ntotal == 0:
            return []

        query_vectors = self._provider.embed([query_text])
        if not query_vectors:
            return []

        q = np.array([query_vectors[0]], dtype=np.float32)
        faiss.normalize_L2(q)

        k = min(top_k, self._index.ntotal)
        distances, indices = self._index.search(q, k)  # type: ignore[call-arg]

        results: list[tuple[str, float]] = []
        for score, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            ku_id = self._id_map.get(int(idx))
            if ku_id is not None:
                results.append((ku_id, float(score)))
        return results

    def is_available(self) -> bool:
        self._load()
        return self._index is not None and self._index.ntotal > 0

    def indexed_count(self) -> int:
        self._load()
        if self._index is None:
            return 0
        return self._index.ntotal

    def rebuild(self, units: list[KnowledgeUnit]) -> int:
        """Full rebuild: drop and re-index all."""
        # Remove old files
        if self._index_path().exists():
            self._index_path().unlink()
        if self._id_map_path().exists():
            self._id_map_path().unlink()

        # Reset in-memory state
        self._index = None
        self._id_map = {}
        self._reverse_map = {}
        self._next_id = 0

        return self.index_units(units)
