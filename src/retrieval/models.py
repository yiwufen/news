"""
检索层数据模型

定义检索请求和响应的数据结构。
支持两种检索模式：
1. 文章检索 (HybridSearcher) - 用于持续运行模式
2. 情报微粒检索 (ParticleSearcher) - 用于任务驱动模式
"""

from dataclasses import dataclass, field
from typing import Any

from src.intent.models import StructuredQuery


@dataclass
class SearchResult:
    """单条检索结果"""

    doc_id: str
    score: float
    source: str  # "bm25" | "vector" | "fusion"
    article: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "doc_id": self.doc_id,
            "score": self.score,
            "source": self.source,
            "article": self.article,
        }


@dataclass
class RetrievalRequest:
    """文章检索请求（持续运行模式使用）"""

    structured_query: StructuredQuery
    top_k: int = 100
    min_score: float = 0.3

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "structured_query": self.structured_query.to_dict(),
            "top_k": self.top_k,
            "min_score": self.min_score,
        }


@dataclass
class RetrievalResult:
    """文章检索结果"""

    articles: list[dict[str, Any]]
    total_count: int
    bm25_count: int = 0
    vector_count: int = 0
    fusion_stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "articles": self.articles,
            "total_count": self.total_count,
            "bm25_count": self.bm25_count,
            "vector_count": self.vector_count,
            "fusion_stats": self.fusion_stats,
        }

    def is_empty(self) -> bool:
        """检查是否为空结果"""
        return len(self.articles) == 0


@dataclass
class ParticleRetrievalRequest:
    """情报微粒检索请求（任务驱动模式使用）

    从持续运行模式产出的情报微粒中检索，
    无需重新从原始文章提取。
    """

    structured_query: StructuredQuery
    top_k: int = 50

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "structured_query": self.structured_query.to_dict(),
            "top_k": self.top_k,
        }


@dataclass
class ParticleRetrievalResult:
    """情报微粒检索结果"""

    particles: list[dict[str, Any]]
    total_count: int
    filters_applied: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "particles": self.particles,
            "total_count": self.total_count,
            "filters_applied": self.filters_applied,
        }

    def is_empty(self) -> bool:
        """检查是否为空结果"""
        return len(self.particles) == 0
