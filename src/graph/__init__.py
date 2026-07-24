"""
Graph 模块

Neo4j 图数据库操作层（Entity ↔ EventCluster 二部图检索）。
图谱写操作统一收口到 ``src.knowledge_graph_sync.KnowledgeGraphSync``。
"""

from src.graph.connection import Neo4jConnection, close_connection, get_connection
from src.graph.knowledge_retrieval import GraphClusterSummary, GraphRetrievalResult, KnowledgeGraphRetriever

__all__ = [
    "Neo4jConnection",
    "get_connection",
    "close_connection",
    "KnowledgeGraphRetriever",
    "GraphClusterSummary",
    "GraphRetrievalResult",
]
