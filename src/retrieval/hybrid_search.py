"""
混合检索器

实现 BM25 + 向量的混合检索。
"""

from datetime import datetime
from typing import Any

from collectors.database import Database
from src.intent.models import StructuredQuery
from src.retrieval.models import RetrievalRequest, RetrievalResult, SearchResult


class HybridSearcher:
    """混合检索器

    实现基于 SQLite 的元数据过滤和简单关键词检索。
    后续可扩展为 BM25 + 向量混合检索。
    """

    def __init__(self, db_path: str = "data/news.db"):
        """初始化检索器

        Args:
            db_path: 数据库路径
        """
        self.db = Database(db_path)

    def search(self, request: RetrievalRequest) -> RetrievalResult:
        """执行检索

        Args:
            request: 检索请求

        Returns:
            RetrievalResult: 检索结果
        """
        query = request.structured_query

        # 1. 从数据库获取所有文章
        all_articles = self.db.get_all_articles()

        # 2. 应用元数据过滤
        filtered = self._apply_filters(all_articles, query)

        # 3. 按时间范围过滤
        if query.time_range:
            filtered = self._filter_by_time_range(filtered, query.time_range)

        # 4. 按实体关键词过滤
        if query.entities:
            filtered = self._filter_by_entities(filtered, query.entities)

        # 5. 限制数量
        top_k = min(request.top_k, len(filtered))
        result_articles = filtered[:top_k]

        return RetrievalResult(
            articles=result_articles,
            total_count=len(filtered),
            bm25_count=len(filtered),  # 当前使用简单过滤，暂无 BM25 分离
            vector_count=0,
            fusion_stats={
                "method": "metadata_filter",
                "original_count": len(all_articles),
                "filtered_count": len(filtered),
            },
        )

    def _apply_filters(
        self,
        articles: list[dict],
        query: StructuredQuery,
    ) -> list[dict]:
        """应用元数据过滤

        Args:
            articles: 文章列表
            query: 结构化查询

        Returns:
            过滤后的文章列表
        """
        result = articles
        filters = query.filters

        # 按分类过滤
        if filters.categories:
            result = [
                a for a in result
                if a.get("category") in filters.categories
            ]

        # 按来源过滤
        if filters.sources:
            result = [
                a for a in result
                if a.get("source_name") in filters.sources
            ]

        # 按可信度过滤
        result = [
            a for a in result
            if a.get("credibility_tier", 3) <= int(1 / filters.min_credibility)
        ]

        return result

    def _filter_by_time_range(
        self,
        articles: list[dict],
        time_range: Any,
    ) -> list[dict]:
        """按时间范围过滤

        Args:
            articles: 文章列表
            time_range: 时间范围

        Returns:
            过滤后的文章列表
        """
        result = []

        for article in articles:
            publish_time = article.get("publish_time", "")
            if not publish_time:
                continue

            try:
                # 解析时间字符串
                if isinstance(publish_time, str):
                    # 处理 ISO 格式
                    pub_date = datetime.fromisoformat(
                        publish_time.replace("Z", "+00:00")
                    ).date()
                else:
                    pub_date = publish_time

                # 检查是否在范围内
                if time_range.start <= pub_date <= time_range.end:
                    result.append(article)
            except (ValueError, TypeError):
                continue

        return result

    def _filter_by_entities(
        self,
        articles: list[dict],
        entities: list[str],
    ) -> list[dict]:
        """按实体关键词过滤

        Args:
            articles: 文章列表
            entities: 实体名称列表

        Returns:
            过滤后的文章列表
        """
        if not entities:
            return articles

        result = []
        for article in articles:
            # 检查标题和内容是否包含实体名称
            title = article.get("title", "").lower()
            content = article.get("content", "").lower()

            for entity in entities:
                entity_lower = entity.lower()
                if entity_lower in title or entity_lower in content:
                    result.append(article)
                    break  # 匹配一个实体即可

        return result

    def bm25_search(
        self,
        query: StructuredQuery,
        top_k: int = 100,
    ) -> list[SearchResult]:
        """BM25 检索（预留接口）

        Args:
            query: 结构化查询
            top_k: 返回数量

        Returns:
            检索结果列表
        """
        # TODO: 实现真正的 BM25 检索
        # 当前使用简单的关键词匹配
        articles = self.db.get_all_articles()

        if query.entities:
            filtered = self._filter_by_entities(articles, query.entities)
        else:
            filtered = articles

        results = []
        for i, article in enumerate(filtered[:top_k]):
            results.append(SearchResult(
                doc_id=article.get("doc_id", f"doc_{i}"),
                score=1.0 / (i + 1),  # 简单排序分数
                source="bm25",
                article=article,
            ))

        return results

    def vector_search(
        self,
        query: StructuredQuery,
        top_k: int = 100,
    ) -> list[SearchResult]:
        """向量检索（预留接口）

        Args:
            query: 结构化查询
            top_k: 返回数量

        Returns:
            检索结果列表
        """
        # TODO: 实现向量检索
        # 当前返回空列表
        return []
