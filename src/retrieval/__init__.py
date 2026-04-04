"""
检索层

提供两种检索模式：
1. HybridSearcher - 文章检索（持续运行模式）
2. ParticleSearcher - 情报微粒检索（任务驱动模式）
"""

from src.retrieval.hybrid_search import HybridSearcher
from src.retrieval.particle_search import ParticleSearcher
from src.retrieval.models import (
    ParticleRetrievalRequest,
    ParticleRetrievalResult,
    RetrievalRequest,
    RetrievalResult,
    SearchResult,
)

__all__ = [
    "HybridSearcher",
    "ParticleSearcher",
    "ParticleRetrievalRequest",
    "ParticleRetrievalResult",
    "RetrievalRequest",
    "RetrievalResult",
    "SearchResult",
]
