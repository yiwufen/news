"""
Neo4j 连接管理

管理 Neo4j 数据库连接池和健康检查。
"""

import os
from contextlib import contextmanager
from typing import Generator

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import ServiceUnavailable


class Neo4jConnection:
    """Neo4j 连接管理类"""

    _instance: "Neo4jConnection | None" = None
    _driver: Driver | None = None

    def __new__(cls) -> "Neo4jConnection":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._driver is None:
            self._init_driver()

    def _init_driver(self) -> None:
        """初始化 Neo4j 驱动"""
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "password")

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

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
        """关闭连接"""
        if self._driver:
            self._driver.close()
            self._driver = None

    def __del__(self):
        """析构时关闭连接"""
        self.close()


# 全局连接实例
_connection: Neo4jConnection | None = None


def get_connection() -> Neo4jConnection:
    """获取全局连接实例"""
    global _connection
    if _connection is None:
        _connection = Neo4jConnection()
    return _connection


def close_connection() -> None:
    """关闭全局连接"""
    global _connection
    if _connection:
        _connection.close()
        _connection = None
