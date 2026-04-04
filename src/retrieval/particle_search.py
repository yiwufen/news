"""
情报微粒检索器

从已存储的情报微粒中检索，而非原始文章。
这是"持续运行模式"产出的数据，供"任务驱动模式"使用。
"""

from datetime import date
from typing import Any

from collectors.database import Database
from src.intent.models import IntentType, StructuredQuery, TimeRange
from src.retrieval.models import ParticleRetrievalRequest, ParticleRetrievalResult


class ParticleSearcher:
    """情报微粒检索器

    从 SQLite 的 intelligence_particles 表检索已提取的情报微粒。
    这是"持续运行模式"的产出，供"任务驱动模式"直接使用，无需重新提取。
    """

    def __init__(self, db_path: str = "data/news.db"):
        """初始化检索器

        Args:
            db_path: 数据库路径
        """
        self.db = Database(db_path)

    def search(self, request: ParticleRetrievalRequest) -> ParticleRetrievalResult:
        """检索情报微粒

        Args:
            request: 检索请求

        Returns:
            ParticleRetrievalResult: 检索结果
        """
        query = request.structured_query

        # 1. 从数据库获取所有情报微粒
        all_particles = self.db.get_all_particles()

        # 2. 按时间范围过滤
        if query.time_range:
            all_particles = self._filter_by_time_range(all_particles, query.time_range)

        # 3. 按实体过滤
        if query.entities:
            all_particles = self._filter_by_entities(all_particles, query.entities)

        # 4. 按事件类型过滤
        if query.filters.event_types:
            all_particles = self._filter_by_event_types(all_particles, query.filters.event_types)

        # 5. 按风险等级过滤
        if query.filters.risk_levels:
            all_particles = self._filter_by_risk_levels(all_particles, query.filters.risk_levels)

        # 6. 按意图类型调整排序
        all_particles = self._sort_by_intent(all_particles, query.intent)

        # 7. 限制数量
        top_k = min(request.top_k, len(all_particles))
        result_particles = all_particles[:top_k]

        return ParticleRetrievalResult(
            particles=result_particles,
            total_count=len(all_particles),
            filters_applied={
                "time_range": query.time_range is not None,
                "entities": len(query.entities) > 0,
                "event_types": query.filters.event_types is not None,
                "risk_levels": query.filters.risk_levels is not None,
            },
        )

    def _filter_by_time_range(
        self,
        particles: list[dict],
        time_range: TimeRange,
    ) -> list[dict]:
        """按时间范围过滤

        Args:
            particles: 情报微粒列表
            time_range: 时间范围

        Returns:
            过滤后的列表
        """
        result = []

        for particle in particles:
            # 从 slice_window 解析时间 (格式: YYYY-WNN 或 YYYY-MM)
            slice_window = particle.get("slice_window", "")
            try:
                if "-W" in slice_window:
                    # 周格式: 2026-W10
                    year, week = slice_window.split("-W")
                    particle_date = date.fromisocalendar(int(year), int(week), 1)
                else:
                    # 月格式: 2026-03
                    parts = slice_window.split("-")
                    if len(parts) == 2:
                        particle_date = date(int(parts[0]), int(parts[1]), 1)
                    else:
                        continue

                if time_range.start <= particle_date <= time_range.end:
                    result.append(particle)
            except (ValueError, TypeError):
                continue

        return result

    def _filter_by_entities(
        self,
        particles: list[dict],
        entities: list[str],
    ) -> list[dict]:
        """按实体过滤

        Args:
            particles: 情报微粒列表
            entities: 实体名称列表

        Returns:
            过滤后的列表
        """
        if not entities:
            return particles

        result = []
        for particle in particles:
            # 检查 entities 字段
            particle_entities = particle.get("entities", [])
            entities_str = " ".join(str(e).lower() for e in particle_entities)

            # 检查摘要
            summary = particle.get("event_summary", "").lower()

            for entity in entities:
                entity_lower = entity.lower()
                if entity_lower in entities_str or entity_lower in summary:
                    result.append(particle)
                    break

        return result

    def _filter_by_event_types(
        self,
        particles: list[dict],
        event_types: list[str],
    ) -> list[dict]:
        """按事件类型过滤

        Args:
            particles: 情报微粒列表
            event_types: 事件类型列表

        Returns:
            过滤后的列表
        """
        return [
            p for p in particles
            if p.get("event_type") in event_types
        ]

    def _filter_by_risk_levels(
        self,
        particles: list[dict],
        risk_levels: list[str],
    ) -> list[dict]:
        """按风险等级过滤

        注意：当前数据库 schema 未存储风险等级，
        此方法为预留接口。

        Args:
            particles: 情报微粒列表
            risk_levels: 风险等级列表

        Returns:
            过滤后的列表
        """
        # TODO: 数据库 schema 需要添加 risk_level 字段
        return particles

    def _sort_by_intent(
        self,
        particles: list[dict],
        intent: IntentType,
    ) -> list[dict]:
        """按意图类型调整排序

        Args:
            particles: 情报微粒列表
            intent: 意图类型

        Returns:
            排序后的列表
        """
        # 按时间倒序（最新在前）
        return sorted(
            particles,
            key=lambda p: p.get("slice_window", ""),
            reverse=True,
        )

    def get_by_ids(self, particle_ids: list[str]) -> list[dict]:
        """根据 ID 列表获取情报微粒

        Args:
            particle_ids: 情报微粒 ID 列表

        Returns:
            情报微粒列表
        """
        all_particles = self.db.get_all_particles()
        id_set = set(particle_ids)
        return [p for p in all_particles if p.get("particle_id") in id_set]

    def get_entities_timeline(
        self,
        entities: list[str],
        time_range: TimeRange | None = None,
    ) -> list[dict]:
        """获取实体时间线

        专用于 ENTITY_TIMELINE 意图。

        Args:
            entities: 实体名称列表
            time_range: 时间范围

        Returns:
            按时间排序的情报微粒列表
        """
        from src.intent.models import QueryFilters

        request = ParticleRetrievalRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=entities,
                time_range=time_range,
                filters=QueryFilters(),
                original_query="",
            ),
            top_k=100,
        )
        result = self.search(request)
        return result.particles
