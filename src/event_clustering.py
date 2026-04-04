"""
事件簇模型、仓储与保守归并服务。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.knowledge_base import KnowledgeUnit


ConflictStatus = Literal["none", "possible", "confirmed"]


class EventCluster(BaseModel):
    """保守归并后的事件视图。"""

    cluster_id: str = Field(default_factory=lambda: f"clu_{uuid4().hex[:12]}")
    cluster_type: str
    title: str
    summary: str
    entity_ids: list[str]
    primary_entity_id: str | None = None
    time_anchor: datetime | date | None = None
    time_range: dict[str, Any] | None = None
    member_ku_ids: list[str]
    source_doc_ids: list[str]
    conflict_status: ConflictStatus = "none"
    cluster_confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    updated_at: datetime


def _normalize_summary(summary: str) -> str:
    return re.sub(r"\s+", "", summary).lower()


def _anchor_date(unit: KnowledgeUnit) -> date:
    anchor = unit.time.event_time or unit.time.published_at
    return anchor.date() if isinstance(anchor, datetime) else anchor


class EventClusterRepository:
    """EventCluster SQLite 仓储。"""

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_clusters (
                    cluster_id TEXT PRIMARY KEY,
                    cluster_type TEXT NOT NULL,
                    primary_entity_id TEXT,
                    time_anchor TEXT,
                    conflict_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_clusters_type ON event_clusters(cluster_type)"
            )
            connection.commit()

    def save_batch(self, clusters: list[EventCluster]) -> int:
        if not clusters:
            return 0
        rows = [
            (
                cluster.cluster_id,
                cluster.cluster_type,
                cluster.primary_entity_id,
                cluster.time_anchor.isoformat() if cluster.time_anchor else None,
                cluster.conflict_status,
                cluster.updated_at.isoformat(),
                json.dumps(cluster.model_dump(mode="json"), ensure_ascii=False),
            )
            for cluster in clusters
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO event_clusters (
                    cluster_id, cluster_type, primary_entity_id, time_anchor,
                    conflict_status, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    cluster_type = excluded.cluster_type,
                    primary_entity_id = excluded.primary_entity_id,
                    time_anchor = excluded.time_anchor,
                    conflict_status = excluded.conflict_status,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                rows,
            )
            connection.commit()
        return len(clusters)

    def get_all(self) -> list[EventCluster]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM event_clusters ORDER BY updated_at DESC, cluster_id ASC"
            ).fetchall()
        return [EventCluster.model_validate(json.loads(row["payload"])) for row in rows]


class EventClusterer:
    """按保守规则归并 EventCluster。"""

    def __init__(self, repository: EventClusterRepository):
        self.repository = repository

    def assign_clusters(
        self,
        units: list[KnowledgeUnit],
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[EventCluster]]:
        existing_clusters = {cluster.cluster_id: cluster for cluster in self.repository.get_all()}
        working_clusters = list(existing_clusters.values())
        touched_clusters: dict[str, EventCluster] = {}
        now = datetime.now(UTC)

        for unit in units:
            matched = self._find_cluster(unit, working_clusters)
            if matched is None:
                entity_ids = [entity.entity_id for entity in unit.entities if entity.entity_id]
                matched = EventCluster(
                    cluster_type=unit.unit_type,
                    title=unit.summary[:80],
                    summary=unit.summary,
                    entity_ids=entity_ids,
                    primary_entity_id=entity_ids[0] if entity_ids else None,
                    time_anchor=unit.time.event_time or unit.time.published_at,
                    time_range=None,
                    member_ku_ids=[unit.ku_id],
                    source_doc_ids=[unit.source.doc_id],
                    conflict_status=unit.conflict_status,
                    cluster_confidence=unit.confidence,
                    updated_at=now,
                )
                working_clusters.append(matched)
            else:
                if unit.ku_id not in matched.member_ku_ids:
                    matched.member_ku_ids.append(unit.ku_id)
                if unit.source.doc_id not in matched.source_doc_ids:
                    matched.source_doc_ids.append(unit.source.doc_id)
                for entity in unit.entities:
                    if entity.entity_id and entity.entity_id not in matched.entity_ids:
                        matched.entity_ids.append(entity.entity_id)
                matched.updated_at = now
                matched.conflict_status = self._merge_conflict_status(
                    matched.conflict_status,
                    unit.conflict_status,
                )
                matched.cluster_confidence = max(matched.cluster_confidence, unit.confidence)
            unit.cluster_id = matched.cluster_id
            touched_clusters[matched.cluster_id] = matched

        clusters = list(touched_clusters.values())
        if persist:
            self.repository.save_batch(clusters)
        return units, clusters

    def _find_cluster(self, unit: KnowledgeUnit, clusters: list[EventCluster]) -> EventCluster | None:
        unit_entity_ids = sorted(entity.entity_id for entity in unit.entities if entity.entity_id)
        unit_anchor = _anchor_date(unit)
        normalized_summary = _normalize_summary(unit.summary)

        for cluster in clusters:
            if cluster.cluster_type != unit.unit_type:
                continue
            if sorted(cluster.entity_ids) != unit_entity_ids:
                continue
            if cluster.time_anchor is None:
                continue
            cluster_anchor = cluster.time_anchor.date() if isinstance(cluster.time_anchor, datetime) else cluster.time_anchor
            if cluster_anchor != unit_anchor:
                continue
            similarity = SequenceMatcher(None, normalized_summary, _normalize_summary(cluster.summary)).ratio()
            if similarity < 0.85:
                continue
            return cluster
        return None

    def _merge_conflict_status(
        self,
        current: ConflictStatus,
        incoming: ConflictStatus,
    ) -> ConflictStatus:
        order: dict[ConflictStatus, int] = {"none": 0, "possible": 1, "confirmed": 2}
        return current if order[current] >= order[incoming] else incoming
