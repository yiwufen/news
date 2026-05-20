"""
事件簇模型、仓储与保守归并服务。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

from src.conflict_detection import ConflictDetector
from src.knowledge_base import KnowledgeUnit, KnowledgeUnitRepository


ConflictStatus = Literal["none", "possible", "confirmed"]
_SAME_DAY_SIMILARITY_THRESHOLD = 0.85
_ADJACENT_DAY_SIMILARITY_THRESHOLD = 0.93

# Module-level singleton for conflict detection
_CONFLICT_DETECTOR = ConflictDetector()


class AggregationVariant(BaseModel):
    """One grouped variant inside an aggregated cluster view."""

    value: str
    ku_ids: list[str] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)
    count: int = 0


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
    representative_ku_id: str | None = None
    member_count: int = 0
    source_count: int = 0
    summary_variants: list[AggregationVariant] = Field(default_factory=list)
    event_time_variants: list[AggregationVariant] = Field(default_factory=list)
    conflict_reasons: list[str] = Field(default_factory=list)
    conflict_details: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime


def _normalize_summary(summary: str) -> str:
    return re.sub(r"\s+", "", summary).lower()


def _anchor_datetime(unit: KnowledgeUnit) -> datetime:
    anchor = unit.time.event_time or unit.time.published_at
    return anchor if isinstance(anchor, datetime) else datetime.combine(anchor, datetime.min.time(), tzinfo=UTC)


def _anchor_date(unit: KnowledgeUnit) -> date:
    return _anchor_datetime(unit).date()


def _date_from_iso_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _cluster_date_bounds(cluster: EventCluster) -> tuple[date, date] | None:
    if cluster.time_range:
        start = _date_from_iso_value(cluster.time_range.get("start"))
        end = _date_from_iso_value(cluster.time_range.get("end"))
        if start is not None and end is not None:
            return (start, end) if start <= end else (end, start)
    if cluster.time_anchor is None:
        return None
    anchor = cluster.time_anchor.date() if isinstance(cluster.time_anchor, datetime) else cluster.time_anchor
    return anchor, anchor


def _hash_entity_ids(sorted_ids: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(sorted_ids)).encode()).hexdigest()[:32]


def _explicit_event_date(unit: KnowledgeUnit) -> str | None:
    if unit.time.event_time is None:
        return None
    return unit.time.event_time.date().isoformat()


def _merge_conflict_status(current: ConflictStatus, incoming: ConflictStatus) -> ConflictStatus:
    order: dict[ConflictStatus, int] = {"none": 0, "possible": 1, "confirmed": 2}
    return current if order[current] >= order[incoming] else incoming


def _unit_representative_sort_key(
    unit: KnowledgeUnit,
    summary_group_sizes: dict[str, int],
) -> tuple[int, float, float, str]:
    return (
        -summary_group_sizes[_normalize_summary(unit.summary)],
        -unit.confidence,
        -_anchor_datetime(unit).timestamp(),
        unit.ku_id,
    )


def _build_variants(
    grouped_units: dict[str, list[KnowledgeUnit]],
    *,
    value_getter: Callable[[KnowledgeUnit], str],
) -> list[AggregationVariant]:
    variants: list[AggregationVariant] = []
    for key, members in grouped_units.items():
        if not key:
            continue
        representative = sorted(
            members,
            key=lambda unit: (
                -unit.confidence,
                -_anchor_datetime(unit).timestamp(),
                unit.ku_id,
            ),
        )[0]
        variants.append(
            AggregationVariant(
                value=value_getter(representative),
                ku_ids=sorted({unit.ku_id for unit in members}),
                source_doc_ids=sorted({unit.source.doc_id for unit in members}),
                count=len({unit.ku_id for unit in members}),
            )
        )
    variants.sort(key=lambda item: (-item.count, item.value))
    return variants


def build_event_cluster_snapshot(
    units: Sequence[KnowledgeUnit],
    *,
    cluster_id: str | None = None,
    updated_at: datetime | None = None,
) -> EventCluster:
    """Recompute an aggregated cluster snapshot from all member units."""

    deduped_units = list({unit.ku_id: unit for unit in units}.values())
    if not deduped_units:
        raise ValueError("cannot build EventCluster from empty units")

    summary_groups: dict[str, list[KnowledgeUnit]] = {}
    for unit in deduped_units:
        summary_groups.setdefault(_normalize_summary(unit.summary), []).append(unit)
    summary_group_sizes = {key: len(value) for key, value in summary_groups.items()}

    representative = sorted(
        deduped_units,
        key=lambda unit: _unit_representative_sort_key(unit, summary_group_sizes),
    )[0]

    explicit_times = [unit.time.event_time for unit in deduped_units if unit.time.event_time is not None]
    if explicit_times:
        time_anchor: datetime | date | None = min(explicit_times)
    else:
        time_anchor = min(unit.time.published_at for unit in deduped_units)

    anchor_values = [_anchor_datetime(unit) for unit in deduped_units]
    time_range = {
        "start": min(anchor_values).isoformat(),
        "end": max(anchor_values).isoformat(),
    }

    entity_ids = sorted(
        {
            entity.entity_id
            for unit in deduped_units
            for entity in unit.entities
            if entity.entity_id
        }
    )
    representative_entity_ids = [
        entity.entity_id for entity in representative.entities if entity.entity_id
    ]
    primary_entity_id = representative_entity_ids[0] if representative_entity_ids else (entity_ids[0] if entity_ids else None)

    summary_variants = _build_variants(
        summary_groups,
        value_getter=lambda unit: unit.summary,
    )

    time_groups: dict[str, list[KnowledgeUnit]] = {}
    for unit in deduped_units:
        event_date = _explicit_event_date(unit)
        if event_date is None:
            continue
        time_groups.setdefault(event_date, []).append(unit)
    event_time_variants = _build_variants(
        time_groups,
        value_getter=lambda unit: _explicit_event_date(unit) or "",
    )

    conflict_reasons: list[str] = []
    explicit_conflict = "none"
    for unit in deduped_units:
        if unit.conflict_status != "none":
            explicit_conflict = _merge_conflict_status(explicit_conflict, unit.conflict_status)
    if explicit_conflict != "none":
        conflict_reasons.append("member_conflict_flag")

    # Run multi-type conflict detection
    conflict_report = _CONFLICT_DETECTOR.detect_conflicts(deduped_units)

    # Add detected conflict types to reasons
    for detail in conflict_report.conflict_details:
        if detail.conflict_type.value == "time_mismatch":
            # Use legacy name for backward compatibility
            reason = "multiple_event_time_values"
        else:
            reason = f"{detail.conflict_type.value}:{detail.field_name}"
        if reason not in conflict_reasons:
            conflict_reasons.append(reason)

    # Determine conflict status
    conflict_status = explicit_conflict
    if conflict_status == "none" and conflict_report.has_conflicts:
        conflict_status = "possible"
    if conflict_report.overall_severity == "high":
        conflict_status = "confirmed"

    # Serialize conflict details for storage
    conflict_details = [
        {
            "type": detail.conflict_type.value,
            "field": detail.field_name,
            "values": detail.values,
            "sources": detail.sources,
            "severity": detail.severity,
            "description": detail.description,
        }
        for detail in conflict_report.conflict_details
    ]

    return EventCluster(
        cluster_id=cluster_id or f"clu_{uuid4().hex[:12]}",
        cluster_type=representative.unit_type,
        title=representative.summary[:80],
        summary=representative.summary,
        entity_ids=entity_ids,
        primary_entity_id=primary_entity_id,
        time_anchor=time_anchor,
        time_range=time_range,
        member_ku_ids=sorted({unit.ku_id for unit in deduped_units}),
        source_doc_ids=sorted({unit.source.doc_id for unit in deduped_units}),
        conflict_status=conflict_status,
        cluster_confidence=max(unit.confidence for unit in deduped_units),
        representative_ku_id=representative.ku_id,
        member_count=len({unit.ku_id for unit in deduped_units}),
        source_count=len({unit.source.doc_id for unit in deduped_units}),
        summary_variants=summary_variants,
        event_time_variants=event_time_variants,
        conflict_reasons=conflict_reasons,
        conflict_details=conflict_details,
        updated_at=updated_at or datetime.now(UTC),
    )


class EventClusterRepository:
    """EventCluster SQLite 仓储。"""

    def __init__(
        self,
        db_path: str = "data/news.db",
        knowledge_units: KnowledgeUnitRepository | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.knowledge_units = knowledge_units
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

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
            self._ensure_column(connection, "event_clusters", "entity_set_hash", "TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cluster_entity_map (
                    entity_id TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    cluster_type TEXT NOT NULL,
                    entity_set_hash TEXT NOT NULL,
                    PRIMARY KEY (entity_id, cluster_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cluster_entity_map_lookup ON cluster_entity_map(cluster_type, entity_set_hash, cluster_id)"
            )
            connection.commit()

    def _load_clusters_from_rows(self, rows: Sequence[sqlite3.Row]) -> list[EventCluster]:
        clusters = [
            EventCluster.model_validate(json.loads(row["payload"]))
            for row in rows
        ]
        return self._repair_clusters(clusters)

    def _repair_clusters(self, clusters: list[EventCluster]) -> list[EventCluster]:
        if not clusters or self.knowledge_units is None:
            return clusters

        repaired: list[EventCluster] = []
        changed = False
        for cluster in clusters:
            if not self._needs_repair(cluster):
                repaired.append(cluster)
                continue

            member_units = self.knowledge_units.get_by_ids(cluster.member_ku_ids)
            if not member_units:
                repaired.append(cluster)
                continue
            repaired_cluster = build_event_cluster_snapshot(
                member_units,
                cluster_id=cluster.cluster_id,
                updated_at=datetime.now(UTC),
            )
            repaired.append(repaired_cluster)
            changed = True

        if changed:
            self.save_batch(repaired)
        return repaired

    def _needs_repair(self, cluster: EventCluster) -> bool:
        if not cluster.member_ku_ids:
            return False
        return any(
            (
                cluster.representative_ku_id is None,
                cluster.member_count != len(set(cluster.member_ku_ids)),
                cluster.source_count != len(set(cluster.source_doc_ids)),
                len(cluster.summary_variants) == 0 and len(cluster.member_ku_ids) > 1,
            )
        )

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
                _hash_entity_ids(sorted(cluster.entity_ids)),
            )
            for cluster in clusters
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO event_clusters (
                    cluster_id, cluster_type, primary_entity_id, time_anchor,
                    conflict_status, updated_at, payload, entity_set_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    cluster_type = excluded.cluster_type,
                    primary_entity_id = excluded.primary_entity_id,
                    time_anchor = excluded.time_anchor,
                    conflict_status = excluded.conflict_status,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload,
                    entity_set_hash = excluded.entity_set_hash
                """,
                rows,
            )
            # Maintain cluster_entity_map index table
            cluster_ids = [c.cluster_id for c in clusters]
            placeholders = ", ".join("?" for _ in cluster_ids)
            connection.execute(
                f"DELETE FROM cluster_entity_map WHERE cluster_id IN ({placeholders})",
                cluster_ids,
            )
            map_rows: list[tuple[str, str, str, str]] = []
            for cluster in clusters:
                sorted_ids = sorted(cluster.entity_ids)
                entity_hash = _hash_entity_ids(sorted_ids)
                for eid in sorted_ids:
                    map_rows.append((eid, cluster.cluster_id, cluster.cluster_type, entity_hash))
            if map_rows:
                connection.executemany(
                    "INSERT OR IGNORE INTO cluster_entity_map (entity_id, cluster_id, cluster_type, entity_set_hash) VALUES (?, ?, ?, ?)",
                    map_rows,
                )
            connection.commit()
        return len(clusters)

    def get_all(self) -> list[EventCluster]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM event_clusters ORDER BY updated_at DESC, cluster_id ASC"
            ).fetchall()
        return self._load_clusters_from_rows(rows)

    def get_by_ids(self, cluster_ids: Sequence[str]) -> list[EventCluster]:
        if not cluster_ids:
            return []
        placeholders = ", ".join("?" for _ in cluster_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM event_clusters WHERE cluster_id IN ({placeholders})",
                list(cluster_ids),
            ).fetchall()
        return self._load_clusters_from_rows(rows)

    def _find_matching_clusters(
        self,
        entity_ids: list[str],
        cluster_type: str,
    ) -> list[EventCluster]:
        """Find clusters with exactly matching entity set and type, using hash index."""
        if not entity_ids:
            return []
        sorted_ids = sorted(entity_ids)
        entity_hash = _hash_entity_ids(sorted_ids)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ec.payload FROM event_clusters ec
                JOIN cluster_entity_map cem ON ec.cluster_id = cem.cluster_id
                WHERE cem.cluster_type = ? AND cem.entity_set_hash = ?
                """,
                (cluster_type, entity_hash),
            ).fetchall()
        clusters = self._load_clusters_from_rows(rows)
        # Verify exact entity set match (hash collision protection)
        return [c for c in clusters if sorted(c.entity_ids) == sorted_ids]

    def find_related(
        self,
        *,
        primary_entity_ids: Iterable[str] | None = None,
        cluster_types: Sequence[str] | None = None,
        time_range: tuple[str, str] | None = None,
    ) -> list[EventCluster]:
        where_clauses: list[str] = []
        params: list[Any] = []
        requested_time_range = time_range
        entity_ids = list(dict.fromkeys(primary_entity_ids or []))
        if entity_ids:
            placeholders = ", ".join("?" for _ in entity_ids)
            where_clauses.append(f"primary_entity_id IN ({placeholders})")
            params.extend(entity_ids)
        if cluster_types:
            placeholders = ", ".join("?" for _ in cluster_types)
            where_clauses.append(f"cluster_type IN ({placeholders})")
            params.extend(cluster_types)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"""
            SELECT payload FROM event_clusters
            {where_sql}
            ORDER BY updated_at DESC, cluster_id ASC
        """
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        clusters = self._load_clusters_from_rows(rows)
        if requested_time_range is None:
            return clusters
        return [
            cluster
            for cluster in clusters
            if self._cluster_overlaps_time_range(cluster, requested_time_range)
        ]

    def _cluster_overlaps_time_range(
        self,
        cluster: EventCluster,
        time_range: tuple[str, str],
    ) -> bool:
        cluster_bounds = _cluster_date_bounds(cluster)
        if cluster_bounds is None:
            return False
        requested_start = _date_from_iso_value(time_range[0])
        requested_end = _date_from_iso_value(time_range[1])
        if requested_start is None or requested_end is None:
            return True
        if requested_start > requested_end:
            requested_start, requested_end = requested_end, requested_start
        cluster_start, cluster_end = cluster_bounds
        return cluster_start <= requested_end and requested_start <= cluster_end


class EventClusterer:
    """按保守规则归并 EventCluster。"""

    def __init__(
        self,
        repository: EventClusterRepository,
        knowledge_units: KnowledgeUnitRepository | None = None,
    ):
        self.repository = repository
        self.knowledge_units = knowledge_units or repository.knowledge_units

    def assign_clusters(
        self,
        units: list[KnowledgeUnit],
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[EventCluster]]:
        clusters_cache = {c.cluster_id: c for c in self.repository.get_all()}
        return self.assign_clusters_with_cache(units, clusters_cache, persist=persist)

    def assign_clusters_with_cache(
        self,
        units: list[KnowledgeUnit],
        clusters_cache: dict[str, EventCluster],
        cluster_members_cache: dict[str, list[KnowledgeUnit]] | None = None,
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[EventCluster]]:
        """
        Assign clusters using an external cache.

        Used for batch processing where multiple documents share cluster context,
        avoiding redundant database loads between documents.
        """
        if cluster_members_cache is None:
            cluster_members_cache = {}
        touched_clusters: dict[str, EventCluster] = {}

        for unit in units:
            matched = self._find_cluster(unit, clusters_cache.values())
            if matched is None:
                matched_members = [unit]
                updated_cluster = build_event_cluster_snapshot(matched_members)
            else:
                matched_members = self._load_cluster_members(
                    matched,
                    cluster_members_cache,
                )
                self._upsert_member(matched_members, unit)
                updated_cluster = build_event_cluster_snapshot(
                    matched_members,
                    cluster_id=matched.cluster_id,
                )
            cluster_members_cache[updated_cluster.cluster_id] = matched_members
            clusters_cache[updated_cluster.cluster_id] = updated_cluster
            unit.cluster_id = updated_cluster.cluster_id
            touched_clusters[updated_cluster.cluster_id] = updated_cluster

        clusters = list(touched_clusters.values())
        if persist:
            self.repository.save_batch(clusters)
        return units, clusters

    def _find_cluster(
        self,
        unit: KnowledgeUnit,
        clusters: Iterable[EventCluster],
    ) -> EventCluster | None:
        unit_entity_ids = sorted(entity.entity_id for entity in unit.entities if entity.entity_id)
        unit_anchor = _anchor_date(unit)
        normalized_summary = _normalize_summary(unit.summary)

        # Use hash-based SQL lookup instead of iterating all clusters
        candidates = self.repository._find_matching_clusters(
            unit_entity_ids, unit.unit_type,
        )

        # Also check in-memory clusters not yet persisted to DB
        for cluster in clusters:
            if cluster.cluster_type != unit.unit_type:
                continue
            if sorted(cluster.entity_ids) != unit_entity_ids:
                continue
            if not any(c.cluster_id == cluster.cluster_id for c in candidates):
                candidates.append(cluster)

        for cluster in candidates:
            # Entity set already verified by _find_matching_clusters or inline check
            cluster_bounds = _cluster_date_bounds(cluster)
            if cluster_bounds is None:
                continue
            cluster_start, cluster_end = cluster_bounds
            if cluster_start <= unit_anchor <= cluster_end:
                day_distance = 0
            elif unit_anchor < cluster_start:
                day_distance = (cluster_start - unit_anchor).days
            else:
                day_distance = (unit_anchor - cluster_end).days
            if day_distance > 1:
                continue
            similarity = SequenceMatcher(None, normalized_summary, _normalize_summary(cluster.summary)).ratio()
            if day_distance == 0 and similarity < _SAME_DAY_SIMILARITY_THRESHOLD:
                continue
            if day_distance == 1 and similarity < _ADJACENT_DAY_SIMILARITY_THRESHOLD:
                continue
            return cluster
        return None

    def _load_cluster_members(
        self,
        cluster: EventCluster,
        cache: dict[str, list[KnowledgeUnit]],
    ) -> list[KnowledgeUnit]:
        cached = cache.get(cluster.cluster_id)
        if cached is not None:
            return cached
        if self.knowledge_units is None or not cluster.member_ku_ids:
            cache[cluster.cluster_id] = []
            return cache[cluster.cluster_id]
        cache[cluster.cluster_id] = self.knowledge_units.get_by_ids(cluster.member_ku_ids)
        return cache[cluster.cluster_id]

    def _upsert_member(self, members: list[KnowledgeUnit], incoming: KnowledgeUnit) -> None:
        for index, member in enumerate(members):
            if member.ku_id == incoming.ku_id:
                members[index] = incoming
                return
        members.append(incoming)
