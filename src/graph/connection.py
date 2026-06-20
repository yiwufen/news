"""
Neo4j 连接管理

管理 Neo4j 数据库连接池和健康检查。

并发安全说明：
- ``get_connection`` / ``Neo4jConnection`` 使用模块级锁保护的 double-checked
  locking 构造进程内唯一的 driver。多个工作线程共享同一个 driver 是安全的
  （Neo4j driver 内部自带线程安全连接池）。
- 已移除 ``__del__``：析构时关闭共享 driver 会在并发 GC 下误关闭正被其他
  线程使用的连接。driver 生命周期绑定进程，退出时由 ``close_connection``
  显式关闭（``cmd_serve`` 注册了 shutdown hook）。
"""

import os
import threading
from contextlib import contextmanager
from typing import Generator

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable

# 默认连接池上限。anyio to_thread 在 serve 侧默认 limiter=16，这里给 driver
# 连接池留出余量，避免高并发时连接获取超时。
_DEFAULT_MAX_CONNECTION_POOL_SIZE = 50
_DEFAULT_CONNECTION_ACQUISITION_TIMEOUT = 30.0


class Neo4jConnection:
    """Neo4j 连接管理类（进程内单例，线程安全构造）。"""

    _instance: "Neo4jConnection | None" = None
    _instance_lock = threading.Lock()
    _driver: Driver | None = None

    def __new__(cls) -> "Neo4jConnection":
        # Double-checked locking：保证高并发首次构造只创建一个实例。
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # __init__ 在 __new__ 之后总会被调用；用锁 + 状态判断保证 driver
        # 只初始化一次，避免并发构造时重复创建 driver。
        if self._driver is None:
            with self._instance_lock:
                if self._driver is None:
                    self._init_driver()

    def _init_driver(self) -> None:
        """初始化 Neo4j 驱动"""
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")

        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=_DEFAULT_MAX_CONNECTION_POOL_SIZE,
            connection_acquisition_timeout=_DEFAULT_CONNECTION_ACQUISITION_TIMEOUT,
        )

    @contextmanager
    def session(self) -> Generator:
        """获取会话上下文管理器"""
        if self._driver is None:
            raise RuntimeError("Neo4j 驱动未初始化")

        session = self._driver.session()
        try:
            yield session
        finally:
            session.close()

    def health_check(self) -> bool:
        """检查连接健康状态"""
        try:
            with self.session() as session:
                result = session.run("RETURN 1 as test")
                return result.single()["test"] == 1
        except ServiceUnavailable:
            return False
        except Exception:
            return False

    def close(self) -> None:
        """关闭连接（进程退出时显式调用）"""
        with self._instance_lock:
            if self._driver:
                self._driver.close()
                self._driver = None


# 模块级连接实例
_connection: Neo4jConnection | None = None
_connection_lock = threading.Lock()


def get_connection() -> Neo4jConnection:
    """获取全局连接实例（线程安全单例）。

    使用 double-checked locking 保证并发首次调用只构造一次。返回的
    ``Neo4jConnection`` 持有进程内唯一的 driver，可被多线程共享。
    """
    global _connection
    if _connection is None:
        with _connection_lock:
            if _connection is None:
                _connection = Neo4jConnection()
    return _connection


def close_connection() -> None:
    """关闭全局连接（进程退出时调用）"""
    global _connection
    with _connection_lock:
        if _connection:
            _connection.close()
            _connection = None
