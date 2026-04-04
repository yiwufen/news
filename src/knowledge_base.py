"""
知识底座核心模型、适配层与仓储。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from collectors.database import Database
from src.schemas import (
    EntityType,
    EventType,
    GraphUpdates,
    IntelligenceParticle,
    Metadata,
    RiskLevel,
    RiskSignal,
    Traceability,
)


ConflictStatus = Literal["none", "possible", "confirmed"]
KnowledgeStatus = Literal["active", "superseded"]
KnowledgeUnitKind = Literal["event", "fact"]


class RawDocument(BaseModel):
    """原始文档。"""

    doc_id: str
    source_type: str
    title: str
    content: str
    source_name: str
    published_at: datetime
    url: str | None = None
    language: str = "zh"
    market: str | None = None
    tickers: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("content 不能为空")
        return content


class EntityRef(BaseModel):
    """知识单元中的实体引用。"""

    entity_id: str | None = None
    mention: str
    entity_type: str | None = None
    role: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)

    @field_validator("mention")
    @classmethod
    def validate_mention(cls, value: str) -> str:
        mention = value.strip()
        if not mention:
            raise ValueError("mention 不能为空")
        return mention


class SourceRef(BaseModel):
    """来源引用。"""

    doc_id: str
    source_name: str
    url: str | None = None


class EvidenceSpan(BaseModel):
    """证据片段。"""

    text: str
    start_offset: int | None = None
    end_offset: int | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("evidence.text 不能为空")
        return text


class TimeRef(BaseModel):
    """时间引用。"""

    event_time: datetime | None = None
    published_at: datetime
    extracted_at: datetime


class RelationHint(BaseModel):
    """潜在关系线索。"""

    relation_type: str
    subject_entity_id: str | None = None
    object_entity_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class KnowledgeUnit(BaseModel):
    """最小可检索证据单元。"""

    ku_id: str = ""
    unit_kind: KnowledgeUnitKind
    unit_type: str
    summary: str
    entities: list[EntityRef]
    source: SourceRef
    evidence: list[EvidenceSpan]
    time: TimeRef
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    tags: list[str] = Field(default_factory=list)
    relation_hints: list[RelationHint] = Field(default_factory=list)
    cluster_id: str | None = None
    conflict_status: ConflictStatus = "none"
    status: KnowledgeStatus = "active"

    @field_validator("summary", "unit_type")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("字符串字段不能为空")
        return text

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[EvidenceSpan]) -> list[EvidenceSpan]:
        if not value:
            raise ValueError("KnowledgeUnit 至少需要一个 evidence")
        return value

    @field_validator("entities")
    @classmethod
    def validate_entities(cls, value: list[EntityRef]) -> list[EntityRef]:
        if not value:
            raise ValueError("KnowledgeUnit 至少需要一个实体 mention")
        return value

    @model_validator(mode="after")
    def assign_stable_ku_id(self) -> KnowledgeUnit:
        payload = {
            "doc_id": self.source.doc_id,
            "unit_kind": self.unit_kind,
            "unit_type": self.unit_type,
            "summary": self.summary,
            "mentions": [entity.mention for entity in self.entities],
            "evidence": [
                {
                    "text": span.text,
                    "start_offset": span.start_offset,
                    "end_offset": span.end_offset,
                }
                for span in self.evidence
            ],
            "event_time": self.time.event_time.isoformat() if self.time.event_time else None,
            "published_at": self.time.published_at.isoformat(),
        }
        digest = hashlib.sha1(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.ku_id = f"ku_{digest[:16]}"
        return self


def ensure_datetime(value: str | datetime) -> datetime:
    """将字符串或 datetime 统一转为 timezone-aware datetime。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def compute_slice_window_from_datetime(value: datetime) -> str:
    """按 ISO 周计算切片窗口。"""
    iso_cal = value.isocalendar()
    return f"{iso_cal[0]}-W{iso_cal[1]:02d}"


def adapt_article_to_raw_document(article: dict) -> RawDocument:
    """将 news_articles 记录适配为 RawDocument。"""
    published_at = ensure_datetime(article["publish_time"])
    ingested_at = ensure_datetime(article.get("created_at") or datetime.now(UTC))
    return RawDocument(
        doc_id=article["doc_id"],
        source_type=article.get("source_type") or "news",
        title=article["title"],
        content=article["content"],
        source_name=article["source_name"],
        published_at=published_at,
        url=None,
        language="zh",
        market=None,
        tickers=[],
        authors=[],
        raw_metadata={},
        ingested_at=ingested_at,
    )


def _map_unit_type_to_event_type(unit_type: str, summary: str) -> EventType | None:
    normalized_unit_type = unit_type.strip().lower()
    unit_type_mapping = {
        "lawsuit": EventType.LEGAL_SUIT,
        "legal_suit": EventType.LEGAL_SUIT,
        "equity_pledge": EventType.EQUITY_PLEDGE,
        "debt_default": EventType.DEBT_DEFAULT,
        "control_change": EventType.REAL_CONTROL_CHANGE,
        "real_control_change": EventType.REAL_CONTROL_CHANGE,
        "policy_sanction": EventType.POLICY_SANCTION,
        "restructuring": EventType.RESTRUCTURING,
    }
    if normalized_unit_type in unit_type_mapping:
        return unit_type_mapping[normalized_unit_type]

    text = f"{unit_type} {summary}"
    if any(keyword in text for keyword in ("诉讼", "司法", "仲裁")):
        return EventType.LEGAL_SUIT
    if any(keyword in text for keyword in ("质押",)):
        return EventType.EQUITY_PLEDGE
    if any(keyword in text for keyword in ("违约", "逾期", "债务")):
        return EventType.DEBT_DEFAULT
    if any(keyword in text for keyword in ("实控", "控制权", "董事长变更")):
        return EventType.REAL_CONTROL_CHANGE
    if any(keyword in text for keyword in ("制裁", "处罚", "监管", "政策")):
        return EventType.POLICY_SANCTION
    if any(keyword in text for keyword in ("閲嶇粍", "骞惰喘", "鏀惰喘", "鍊哄姟閲嶇粍")):
        return EventType.RESTRUCTURING
    return None


def _infer_risk_level(unit: KnowledgeUnit) -> RiskLevel:
    if unit.conflict_status == "confirmed":
        return RiskLevel.HIGH
    if unit.confidence >= 0.9:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


class KnowledgeToLegacyParticleAdapter:
    """KnowledgeUnit 到 legacy IntelligenceParticle 的显式适配层。"""

    def _resolve_legacy_event_type(self, unit: KnowledgeUnit) -> EventType | None:
        return _map_unit_type_to_event_type(unit.unit_type, unit.summary)

    def to_legacy_row(self, unit: KnowledgeUnit) -> dict[str, object] | None:
        event_type = self._resolve_legacy_event_type(unit)
        if event_type is None:
            return None
        slice_window = compute_slice_window_from_datetime(unit.time.published_at)
        entities = [entity.mention for entity in unit.entities]
        return {
            "particle_id": unit.ku_id,
            "slice_window": slice_window,
            "event_type": event_type.value,
            "event_summary": unit.summary,
            "entities": entities,
            "source_doc_ids": [unit.source.doc_id],
        }

    def to_legacy_particle(self, unit: KnowledgeUnit) -> IntelligenceParticle | None:
        event_type = self._resolve_legacy_event_type(unit)
        if event_type is None:
            return None
        risk_level = _infer_risk_level(unit)
        source_name = unit.source.url or unit.source.source_name
        event_time = unit.time.event_time or unit.time.published_at
        return IntelligenceParticle(
            id=unit.ku_id or f"evt_{uuid4().hex[:12]}",
            metadata=Metadata(
                source=source_name,
                event_time=event_time.date(),
                reliability=unit.confidence,
            ),
            risk_signal=RiskSignal(
                type=event_type,
                level=risk_level,
                description=unit.summary,
            ),
            graph_updates=GraphUpdates(),
            traceability=Traceability(
                source_doc_ids=[unit.source.doc_id],
                is_contradictory=unit.conflict_status != "none",
            ),
        )


class _SQLiteRepository:
    """共享 SQLite 基础设施。"""

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


class RawDocumentRepository:
    """RawDocument 适配仓储。"""

    def __init__(self, db_path: str = "data/news.db"):
        self.db = Database(db_path)
        self.log_repo = KnowledgeProcessingLogRepository(db_path)

    def iter_documents(
        self,
        batch_size: int = 10,
        time_window: str | None = None,
        incremental: bool = True,
    ) -> Iterator[list[RawDocument]]:
        documents = [adapt_article_to_raw_document(article) for article in self.db.get_all_articles()]

        if incremental:
            processed_doc_ids = self.log_repo.get_processed_doc_ids()
            documents = [doc for doc in documents if doc.doc_id not in processed_doc_ids]

        if time_window:
            documents = [
                doc for doc in documents
                if compute_slice_window_from_datetime(doc.published_at) == time_window
            ]

        for index in range(0, len(documents), batch_size):
            yield documents[index:index + batch_size]


class KnowledgeUnitRepository(_SQLiteRepository):
    """KnowledgeUnit 仓储。"""

    def __init__(self, db_path: str = "data/news.db"):
        super().__init__(db_path)
        self._init_table()

    def _init_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_units (
                    ku_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    unit_kind TEXT NOT NULL,
                    unit_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    primary_mentions TEXT NOT NULL,
                    event_time TEXT,
                    published_at TEXT NOT NULL,
                    cluster_id TEXT,
                    conflict_status TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_units_doc_id ON knowledge_units(doc_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_units_cluster_id ON knowledge_units(cluster_id)"
            )
            connection.commit()

    def save_batch(self, units: list[KnowledgeUnit]) -> int:
        if not units:
            return 0
        rows = [
            (
                unit.ku_id,
                unit.source.doc_id,
                unit.unit_kind,
                unit.unit_type,
                unit.summary,
                json.dumps([entity.mention for entity in unit.entities], ensure_ascii=False),
                unit.time.event_time.isoformat() if unit.time.event_time else None,
                unit.time.published_at.isoformat(),
                unit.cluster_id,
                unit.conflict_status,
                unit.status,
                json.dumps(unit.model_dump(mode="json"), ensure_ascii=False),
            )
            for unit in units
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO knowledge_units (
                    ku_id, doc_id, unit_kind, unit_type, summary, primary_mentions,
                    event_time, published_at, cluster_id, conflict_status, status, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ku_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    unit_kind = excluded.unit_kind,
                    unit_type = excluded.unit_type,
                    summary = excluded.summary,
                    primary_mentions = excluded.primary_mentions,
                    event_time = excluded.event_time,
                    published_at = excluded.published_at,
                    cluster_id = excluded.cluster_id,
                    conflict_status = excluded.conflict_status,
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
            connection.commit()
        return len(units)

    def get_all(self) -> list[KnowledgeUnit]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM knowledge_units ORDER BY published_at DESC, ku_id ASC"
            ).fetchall()
        return [KnowledgeUnit.model_validate(json.loads(row["payload"])) for row in rows]


class KnowledgeProcessingLogRepository(_SQLiteRepository):
    """离线知识化处理日志。"""

    def __init__(self, db_path: str = "data/news.db"):
        super().__init__(db_path)
        self._init_table()

    def _init_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_processing_log (
                    doc_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    knowledge_units_count INTEGER DEFAULT 0,
                    entities_count INTEGER DEFAULT 0,
                    clusters_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_processing_status ON knowledge_processing_log(status)"
            )
            connection.commit()

    def get_processed_doc_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT doc_id FROM knowledge_processing_log WHERE status = 'success'"
            ).fetchall()
        return {row["doc_id"] for row in rows}

    def log_batch(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        data = [
            (
                record["doc_id"],
                record["status"],
                record.get("knowledge_units_count", 0),
                record.get("entities_count", 0),
                record.get("clusters_count", 0),
                record.get("error_message"),
            )
            for record in records
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO knowledge_processing_log (
                    doc_id, status, knowledge_units_count, entities_count, clusters_count, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    status = excluded.status,
                    knowledge_units_count = excluded.knowledge_units_count,
                    entities_count = excluded.entities_count,
                    clusters_count = excluded.clusters_count,
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                data,
            )
            connection.commit()
