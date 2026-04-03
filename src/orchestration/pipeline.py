"""
Pipeline 入口

统一的流水线入口 API。
"""

from typing import Any

from src.orchestration.graph import run_pipeline
from src.orchestration.state import GraphState


class Pipeline:
    """情报分析流水线

    统一的入口 API，封装完整的分析流程。
    """

    def __init__(self):
        self._last_state: GraphState | None = None

    def run(
        self,
        articles: list[dict] | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """运行流水线

        Args:
            articles: 新闻文章列表
            query: 分析查询

        Returns:
            分析结果
        """
        result = run_pipeline(articles=articles, query=query)

        # 保存最后状态
        if isinstance(result, GraphState):
            self._last_state = result
            return result.to_dict()

        return result

    def analyze(
        self,
        target_entity: str,
    ) -> dict[str, Any]:
        """分析指定实体

        Args:
            target_entity: 目标实体名称

        Returns:
            分析结果
        """
        return self.run(query=target_entity)

    def process_articles(
        self,
        articles: list[dict],
    ) -> dict[str, Any]:
        """处理文章列表

        Args:
            articles: 文章列表

        Returns:
            处理结果
        """
        return self.run(articles=articles)

    def get_last_state(self) -> GraphState | None:
        """获取最后状态"""
        return self._last_state


# 全局 Pipeline 实例
_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    """获取全局 Pipeline 实例"""
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline
