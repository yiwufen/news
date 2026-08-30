"""FAISS-backed vector index for KnowledgeUnit dense retrieval."""

from __future__ import annotations

import json
import logging
import os
import threading
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

    并发说明：
    - 只读路径（``search``/``is_available``/``indexed_count``）在 serve 进程中
      被多线程共享调用，``_load`` 使用 double-checked locking 保证首次加载只
      读盘一次，并记录索引文件 mtime；检测到离线 ingestion 写出新索引时
      惰性 reload，避免长期读到陈旧数据。
    - 写路径（``index_units``/``rebuild``）只在离线进程调用，与 serve 的共享
      实例进程隔离，不受读路径加锁影响。
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

        # Concurrency: protect lazy load + mtime-driven reload.
        self._lock = threading.Lock()
        self._loaded_index_mtime: float | None = None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self._vec_dir / _INDEX_FILE

    def _id_map_path(self) -> Path:
        return self._vec_dir / _ID_MAP_FILE

    def _index_mtime(self) -> float | None:
        """Current on-disk index file mtime, or None if file is absent."""
        path = self._index_path()
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _load(self) -> None:
        """Load existing index and ID map from disk (if present).

        Thread-safe double-checked locking. Records the on-disk index mtime so
        the caller can detect subsequent updates and trigger a reload.
        """
        if self._index is not None:
            return

        with self._lock:
            if self._index is not None:
                return
            self._load_locked()

    def _load_locked(self) -> None:
        """Perform the actual disk read. Caller must hold ``self._lock``."""
        current_mtime = self._index_mtime()

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

        self._loaded_index_mtime = current_mtime

    def _maybe_reload_locked(self) -> None:
        """Reload if the on-disk index changed since the last load.

        Caller must hold ``self._lock``. Cheap mtime check; only does an actual
        reload when the file was updated (e.g. offline ingestion rebuilt it).
        """
        if self._loaded_index_mtime is None and self._index is None:
            self._load_locked()
            return

        current_mtime = self._index_mtime()
        if current_mtime != self._loaded_index_mtime:
            logger.info(
                "FAISS index changed on disk (mtime %s → %s), reloading",
                self._loaded_index_mtime,
                current_mtime,
            )
            self._index = None
            self._load_locked()

    def _ensure_fresh(self) -> None:
        """Ensure the in-memory index reflects the latest on-disk file.

        Entry point for read paths: cheap when the file is unchanged (one
        ``stat`` + lock-free early return), reloads only when mtime changes.
        """
        if self._index is None:
            self._load()
            return
        if self._index_mtime() == self._loaded_index_mtime:
            return
        with self._lock:
            self._maybe_reload_locked()

    def _save(self) -> None:
        """Persist current index and ID map to disk atomically."""
        if self._index is None:
            return
        self._vec_dir.mkdir(parents=True, exist_ok=True)
        # Write to temp files, then atomic rename
        idx_tmp = str(self._index_path()) + ".tmp"
        idmap_tmp = str(self._id_map_path()) + ".tmp"
        try:
            faiss.write_index(self._index, idx_tmp)
            raw = {str(k): v for k, v in self._id_map.items()}
            Path(idmap_tmp).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            os.replace(idx_tmp, str(self._index_path()))
            os.replace(idmap_tmp, str(self._id_map_path()))
        except Exception:
            # Clean up temp files on failure
            for tmp in (idx_tmp, idmap_tmp):
                try:
                    Path(tmp).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        # Refresh mtime after write so subsequent _ensure_fresh doesn't reload.
        self._loaded_index_mtime = self._index_mtime()

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
        self._ensure_fresh()
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

    def score_ids(self, query_text: str, ku_ids: list[str]) -> dict[str, float]:
        """Cosine similarity of the query against specific ku_ids.

        Unlike ``search`` (global top-k), this scores an arbitrary candidate
        subset — the entity route needs semantic scores for every recalled
        candidate, not just the globally nearest ones. KU ids missing from the
        index are simply absent from the returned dict.
        """
        self._ensure_fresh()
        if self._index is None or self._index.ntotal == 0:
            return {}

        id_to_ku: dict[int, str] = {}
        int_ids: list[int] = []
        for ku_id in ku_ids:
            int_id = self._reverse_map.get(ku_id)
            if int_id is not None:
                id_to_ku[int_id] = ku_id
                int_ids.append(int_id)
        if not int_ids:
            return {}

        query_vectors = self._provider.embed([query_text])
        if not query_vectors:
            return {}

        q = np.array([query_vectors[0]], dtype=np.float32)
        faiss.normalize_L2(q)

        # IndexIDMap does not implement reconstruct/reconstruct_batch in all
        # faiss builds (raises "not implemented for this type of index"), so go
        # through the wrapped flat index directly: id_map maps internal
        # position → external id, invert it once and reconstruct from the
        # inner IndexFlatIP, which always supports reconstruct.
        inner = self._index.index  # type: ignore[attr-defined]
        external_ids = faiss.vector_to_array(self._index.id_map)  # type: ignore[attr-defined]
        internal_of = {int(ext): pos for pos, ext in enumerate(external_ids)}
        missing = [i for i in int_ids if i not in internal_of]
        if missing:
            # Stale reverse map (index reloaded/rebuilt under us) — drop them.
            int_ids = [i for i in int_ids if i in internal_of]
            if not int_ids:
                return {}
        arr = np.stack(
            [inner.reconstruct(internal_of[i]) for i in int_ids]  # type: ignore[call-arg]
        ).astype(np.float32)
        # Stored vectors are already L2-normalized at index time; normalize the
        # reconstructed copy defensively in case of float drift.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        arr = arr / norms

        scores = (arr @ q[0]).astype(np.float64)
        return {id_to_ku[i]: float(s) for i, s in zip(int_ids, scores)}

    def is_available(self) -> bool:
        self._ensure_fresh()
        return self._index is not None and self._index.ntotal > 0

    def indexed_count(self) -> int:
        self._ensure_fresh()
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
        with self._lock:
            self._index = None
            self._id_map = {}
            self._reverse_map = {}
            self._next_id = 0
            self._loaded_index_mtime = None

        return self.index_units(units)
