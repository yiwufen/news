"""Serve 进程只读单例工厂。

为什么需要它：
- serve 进程下 MCP tool 经 anyio.to_thread 并发执行。若每个 worker 各自
  ``new KnowledgeSearcher`` / ``new VectorIndex``，会各自触发 FAISS
  ``read_index``（单份约 83MB）和 repo ``_init_table``（含全表扫描）。并发
  越高，内存与延迟线性恶化，在 4GB 部署宿主机上极易 OOM。
- 本模块在 serve 模式下提供进程级共享单例：无论多少 worker，内存里始终只有
  一份 FAISS 索引和一套 repo。

边界：
- 仅在 ``KNOWLEDGE_SERVE_MODE=1`` 时启用（由 ``cmd_serve`` 设置）。CLI 单次
  调用 / 测试默认走原有 per-call 构造，行为不变。
- 不缓存离线写路径对象；离线 ingestion 在独立进程，不读本模块。
- 单例对象在 serve 路径下是只读检索用途，无共享可变状态。
"""

from __future__ import annotations

import os
import threading

from src.entities import EntityRepository
from src.graph.connection import get_connection
from src.retrieval.knowledge_search import KnowledgeSearcher

_SERVE_MODE_ENV = "KNOWLEDGE_SERVE_MODE"

# 单独的锁保护 searcher 构造。lru_cache 自身线程安全，但 KnowledgeSearcher
# 构造较重且可能因为内部 embedding provider 在无配置时抛异常——失败时不希望
# 缓存住异常，所以用显式锁 + 空字典缓存，失败可重试。
_searcher_lock = threading.Lock()
_searcher_cache: dict[str, KnowledgeSearcher] = {}

_entity_repo_lock = threading.Lock()
_entity_repo_cache: dict[str, EntityRepository] = {}

_graph_retriever_lock = threading.Lock()


def is_serve_mode() -> bool:
    """Whether the current process runs as the MCP serve process."""
    return os.environ.get(_SERVE_MODE_ENV, "") == "1"


def get_searcher(db_path: str) -> KnowledgeSearcher:
    """Return the shared ``KnowledgeSearcher`` for serve mode.

    Construction failures are not cached: a later call retries. The cached
    instance internally owns the single VectorIndex + repos, so all to_thread
    workers share one FAISS index in memory.
    """
    cached = _searcher_cache.get(db_path)
    if cached is not None:
        return cached
    with _searcher_lock:
        cached = _searcher_cache.get(db_path)
        if cached is not None:
            return cached
        searcher = KnowledgeSearcher(db_path)
        _searcher_cache[db_path] = searcher
        return searcher


def get_entity_repository(db_path: str) -> EntityRepository:
    """Return the shared ``EntityRepository`` for serve mode."""
    cached = _entity_repo_cache.get(db_path)
    if cached is not None:
        return cached
    with _entity_repo_lock:
        cached = _entity_repo_cache.get(db_path)
        if cached is not None:
            return cached
        repo = EntityRepository(db_path)
        _entity_repo_cache[db_path] = repo
        return repo


def get_graph_retriever(db_path: str):  # type: ignore[no-untyped-def]
    """Return the shared ``KnowledgeGraphRetriever`` for serve mode.

    Reuses the shared ``EntityRepository`` and ``EventClusterRepository`` (via
    the shared ``KnowledgeSearcher``) so repo ``_init_table`` only runs once.
    The Neo4j connection is the process-global single driver.
    """
    from src.graph.knowledge_retrieval import KnowledgeGraphRetriever

    searcher = get_searcher(db_path)
    with _graph_retriever_lock:
        # KnowledgeGraphRetriever is stateless aside from its repo/connection
        # handles; cheap to build, but keep it tied to the shared deps.
        return KnowledgeGraphRetriever(
            db_path=db_path,
            connection=get_connection(),
            entity_repo=searcher.entities,
            cluster_repo=searcher.clusters,
        )


def clear_serve_singletons() -> None:
    """Drop cached singletons. Intended for tests only."""
    with _searcher_lock:
        _searcher_cache.clear()
    with _entity_repo_lock:
        _entity_repo_cache.clear()


__all__ = [
    "is_serve_mode",
    "get_searcher",
    "get_entity_repository",
    "get_graph_retriever",
    "clear_serve_singletons",
]
