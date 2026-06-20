"""并发安全回归测试。

覆盖本轮并发改造的关键不变量：
- Neo4j 全局连接在并发首次构造下只建一次（防 driver race 崩溃）。
- VectorIndex._load 并发首调用只读盘一次（防多份 FAISS 副本）。
- serve 单例工厂在 serve 模式下返回共享对象。
- MCPCallLogger 用单写线程消费队列（无 per-call 线程）。

测试不依赖真实 Neo4j / FAISS 磁盘文件，全部 mock。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest

from src.admin import mcp_logger as mcp_logger_module
from src.graph import connection as connection_module


# ----------------------------------------------------------------------
# Neo4j 连接：并发首次构造只建一个 driver
# ----------------------------------------------------------------------


# 测试间共享的 driver mock 引用（由 autouse fixture 注入）。
_driver_mock: mock.MagicMock | None = None


@pytest.fixture(autouse=True)
def _reset_neo4j_singleton(monkeypatch):
    """每个测试前后都重置模块级单例与类级单例，避免相互污染。"""
    global _driver_mock
    connection_module._connection = None
    connection_module.Neo4jConnection._instance = None
    connection_module.Neo4jConnection._driver = None
    with mock.patch.object(connection_module.GraphDatabase, "driver") as drv:
        drv.return_value = mock.MagicMock()
        _driver_mock = drv
        yield
    _driver_mock = None
    connection_module._connection = None
    connection_module.Neo4jConnection._instance = None
    connection_module.Neo4jConnection._driver = None


def test_get_connection_returns_same_instance_under_concurrency():
    """32 个线程并发 get_connection，全部拿到同一个对象，driver 只建一次。"""
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda _: connection_module.get_connection(), range(64)))

    assert len(set(id(r) for r in results)) == 1, "并发下应只返回一个连接实例"
    # driver 只初始化一次
    assert _driver_mock is not None and _driver_mock.call_count == 1


def test_close_connection_clears_singleton():
    conn = connection_module.get_connection()
    # close 把模块级引用与 driver 都清空
    connection_module.close_connection()
    assert connection_module._connection is None
    assert conn._driver is None
    # 再次取：Neo4jConnection 是进程级单例类，对象同一引用，但 driver 重建
    conn2 = connection_module.get_connection()
    assert conn2 is conn  # 单例类，对象不变
    assert conn2._driver is not None  # driver 已重建


# ----------------------------------------------------------------------
# VectorIndex._load：并发首调用只读盘一次
# ----------------------------------------------------------------------


def test_vector_index_load_is_thread_safe(tmp_path, monkeypatch):
    """并发首调用 _load，faiss.read_index 只被调用一次。"""
    import numpy as np

    # 准备假的 index 文件路径使 _index_mtime 返回非 None
    idx_dir = tmp_path / "vector_db"
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / "faiss.index").write_bytes(b"placeholder")
    (idx_dir / "id_map.json").write_text("{}", encoding="utf-8")

    fake_index = mock.MagicMock()
    fake_index.ntotal = 0
    fake_index.d = 8

    call_count = {"n": 0}
    lock = threading.Lock()

    def fake_read_index(_path):
        with lock:
            call_count["n"] += 1
        # 模拟读盘耗时，放大竞争窗口
        time.sleep(0.02)
        return fake_index

    import src.retrieval.vector_index as vi_module

    monkeypatch.setattr(vi_module.faiss, "read_index", fake_read_index)

    provider = mock.MagicMock()
    vi = vi_module.VectorIndex(str(tmp_path / "news.db"), provider)

    with ThreadPoolExecutor(max_workers=16) as pool:
        # 并发触发懒加载
        list(pool.map(lambda _: vi._load(), range(32)))

    assert call_count["n"] == 1, "并发首加载应只读盘一次"


def test_vector_index_reload_on_mtime_change(tmp_path, monkeypatch):
    """索引文件 mtime 变化后，_ensure_fresh 触发一次 reload。"""
    idx_dir = tmp_path / "vector_db"
    idx_dir.mkdir(parents=True, exist_ok=True)
    index_file = idx_dir / "faiss.index"
    index_file.write_bytes(b"v1")
    (idx_dir / "id_map.json").write_text("{}", encoding="utf-8")

    fake_index = mock.MagicMock()
    fake_index.ntotal = 1
    fake_index.d = 8
    reads = {"n": 0}

    def fake_read_index(_path):
        reads["n"] += 1
        return fake_index

    import src.retrieval.vector_index as vi_module

    monkeypatch.setattr(vi_module.faiss, "read_index", fake_read_index)

    provider = mock.MagicMock()
    vi = vi_module.VectorIndex(str(tmp_path / "news.db"), provider)

    vi.is_available()  # 首次加载
    assert reads["n"] == 1

    # 未变化：不 reload
    vi.is_available()
    assert reads["n"] == 1

    # 模拟离线写：更新文件 mtime
    time.sleep(0.05)
    index_file.write_bytes(b"v2")
    import os

    os.utime(index_file, None)

    vi.is_available()  # mtime 变 → reload
    assert reads["n"] == 2


# ----------------------------------------------------------------------
# serve 单例工厂
# ----------------------------------------------------------------------


def test_serve_singletons_share_objects(monkeypatch, tmp_path):
    """get_searcher 缓存共享对象；clear_serve_singletons 清空后重新构造。

    is_serve_mode() 只决定 graph.py 是否调用工厂；工厂本身始终缓存。
    """
    from src.retrieval import serve_singletons as ss

    call_count = {"n": 0}

    def fake_ctor(db_path):
        call_count["n"] += 1
        return mock.MagicMock()

    monkeypatch.setattr(ss, "KnowledgeSearcher", fake_ctor)
    ss.clear_serve_singletons()

    # 连续多次调用返回同一对象，只构造一次
    a = ss.get_searcher("db")
    b = ss.get_searcher("db")
    c = ss.get_searcher("db2")
    assert a is b
    assert a is not c  # 不同 db_path 不同实例
    assert call_count["n"] == 2

    # 不同 db_path 不会互相影响
    ss.clear_serve_singletons()
    call_count["n"] = 0
    d = ss.get_searcher("db")
    assert call_count["n"] == 1
    assert d is not a  # 清空后是新对象


def test_is_serve_mode_reflects_env(monkeypatch):
    """KNOWLEDGE_SERVE_MODE 环境变量控制 is_serve_mode()。"""
    from src.retrieval import serve_singletons as ss

    monkeypatch.delenv("KNOWLEDGE_SERVE_MODE", raising=False)
    assert ss.is_serve_mode() is False

    monkeypatch.setenv("KNOWLEDGE_SERVE_MODE", "1")
    assert ss.is_serve_mode() is True

    monkeypatch.setenv("KNOWLEDGE_SERVE_MODE", "0")
    assert ss.is_serve_mode() is False


# ----------------------------------------------------------------------
# MCPCallLogger：单写线程消费队列
# ----------------------------------------------------------------------


def test_mcp_logger_uses_single_writer_thread(monkeypatch, tmp_path):
    """log() 不创建 per-call 线程；记录经单写线程落库。"""
    db_path = tmp_path / "logs.db"

    created_threads = {"n": 0}
    real_thread_init = threading.Thread.__init__

    def counting_init(self, *args, **kwargs):
        created_threads["n"] += 1
        return real_thread_init(self, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "__init__", counting_init)

    logger = mcp_logger_module.MCPCallLogger(str(db_path))
    # __init__ 启动 1 个写线程
    assert created_threads["n"] == 1

    # 连续 log 100 次：不应再创建任何线程（旧的实现每次都会 new Thread）
    for _ in range(100):
        logger.log(
            tool_name="search_knowledge",
            intent="ENTITY_OVERVIEW",
            entity_count=1,
        )

    assert created_threads["n"] == 1, "不应为每条 log 创建线程"

    # 等待写线程消费
    logger.stop()

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM mcp_call_log").fetchone()[0]
    conn.close()
    assert count == 100


def test_mcp_logger_safe_under_concurrent_puts(tmp_path):
    """多线程并发 log 不阻塞、不丢记录（单写线程串行消费）。"""
    db_path = tmp_path / "logs.db"
    logger = mcp_logger_module.MCPCallLogger(str(db_path))

    def log_many(n: int) -> None:
        for i in range(n):
            logger.log(tool_name="search_knowledge", entity_count=i)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(log_many, [50] * 8))  # 共 400 条

    logger.stop()

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM mcp_call_log").fetchone()[0]
    conn.close()
    assert count == 400


# ----------------------------------------------------------------------
# search_knowledge async：to_thread 调度，不阻塞事件循环
# ----------------------------------------------------------------------


def test_search_knowledge_is_coroutine():
    """search_knowledge 注册为 async，返回协程而非直接结果。"""
    import inspect

    from src.mcp_server import create_server

    server = create_server()
    # FastMCP 把 tool 挂在 _tool_manager；取底层函数校验
    tool = server._tool_manager.get_tool("search_knowledge")
    assert tool is not None
    assert inspect.iscoroutinefunction(tool.fn)


def test_search_knowledge_offloads_to_thread(monkeypatch):
    """run_pipeline 在工作线程执行（主线程 id 不同）。"""
    from src.mcp_server import create_server

    main_thread = threading.get_ident()
    seen: dict[str, int | None] = {"worker": None}

    def fake_run_pipeline(**kwargs):
        seen["worker"] = threading.get_ident()
        result = mock.MagicMock()
        result.to_dict.return_value = {"ok": True}
        return result

    monkeypatch.setattr("src.orchestration.graph.run_pipeline", fake_run_pipeline)

    server = create_server()
    tool = server._tool_manager.get_tool("search_knowledge")
    assert tool is not None

    async def call_it():
        return await tool.fn(entities=["比亚迪"])

    result = asyncio.run(call_it())
    assert result == {"ok": True}
    assert seen["worker"] is not None
    assert seen["worker"] != main_thread, "阻塞逻辑应跑到工作线程"
