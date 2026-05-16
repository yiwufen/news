"""
Core knowledge models and SQLite repositories.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal, Sequence

from pydantic import BaseModel, Field, field_validator, model_validator

from collectors.database import Database


ConflictStatus = Literal["none", "possible", "confirmed"]
KnowledgeStatus = Literal["active", "superseded"]
KnowledgeUnitKind = Literal["event", "fact"]


class RawDocument(BaseModel):
    """Raw input document."""

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
            raise ValueError("content cannot be empty")
        return content


class EntityRef(BaseModel):
    """Entity reference inside one knowledge unit."""

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
            raise ValueError("mention cannot be empty")
        return mention


class SourceRef(BaseModel):
    """Source reference."""

    doc_id: str
    source_name: str
    url: str | None = None


class EvidenceSpan(BaseModel):
    """Evidence snippet."""

    text: str
    start_offset: int | None = None
    end_offset: int | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("evidence.text cannot be empty")
        return text


# Time resolution types for event_time standardization
TimeResolutionType = Literal["absolute", "relative", "fuzzy", "unresolved"]


class TimeRef(BaseModel):
    """Time reference."""

    event_time: datetime | None = None
    published_at: datetime
    extracted_at: datetime
    # Time normalization metadata
    event_time_resolution: TimeResolutionType | None = None
    raw_event_time_expression: str | None = None


class RelationHint(BaseModel):
    """Potential relationship hint extracted from text.

    LLM fills subject_mention/object_mention; pipeline backfills entity_ids.
    """

    relation_type: str
    subject_mention: str | None = None
    object_mention: str | None = None
    subject_entity_id: str | None = None
    object_entity_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class KnowledgeUnit(BaseModel):
    """Smallest retrievable evidence unit."""

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
            raise ValueError("string field cannot be empty")
        return text

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[EvidenceSpan]) -> list[EvidenceSpan]:
        if not value:
            raise ValueError("KnowledgeUnit requires at least one evidence span")
        return value

    @model_validator(mode="after")
    def assign_stable_ku_id(self) -> KnowledgeUnit:
        if self.ku_id:
            return self
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
    """Normalize a string or datetime into a timezone-aware datetime."""
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
    """Build an ISO-week slice window string."""
    iso_cal = value.isocalendar()
    return f"{iso_cal[0]}-W{iso_cal[1]:02d}"


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        deduped.append(text)
        seen.add(text)
    return deduped


def build_knowledge_unit_search_sections(
    unit: KnowledgeUnit,
    entity_names: Sequence[str] | None = None,
) -> dict[str, str]:
    """Build canonical search/index text sections for one knowledge unit.

    Chinese text is segmented with jieba so that FTS5 can match individual
    words rather than whole character runs.
    """
    from src.chinese_text import segment_chinese

    mentions = _dedupe_strings([entity.mention for entity in unit.entities])
    names = _dedupe_strings(list(entity_names or mentions))
    evidence = _dedupe_strings([span.text for span in unit.evidence])
    tags = _dedupe_strings(unit.tags)
    return {
        "summary": segment_chinese(unit.summary),
        "unit_type": segment_chinese(unit.unit_type),
        "source_name": unit.source.source_name,
        "evidence_text": segment_chinese(" ".join(evidence)),
        "entity_mentions": segment_chinese(" ".join(mentions)),
        "entity_names": segment_chinese(" ".join(names)),
        "tags": segment_chinese(" ".join(tags)),
    }


def build_knowledge_unit_search_text(
    unit: KnowledgeUnit,
    entity_names: Sequence[str] | None = None,
) -> str:
    """Flatten search sections into one text payload."""
    sections = build_knowledge_unit_search_sections(unit, entity_names=entity_names)
    return " ".join(value for value in sections.values() if value).strip()


def adapt_article_to_raw_document(article: dict) -> RawDocument:
    """Adapt a `news_articles` record into RawDocument."""
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


class _SQLiteRepository:
    """Shared SQLite helpers."""

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection


class RawDocumentRepository:
    """RawDocument adapter repository."""

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
                doc
                for doc in documents
                if compute_slice_window_from_datetime(doc.published_at) == time_window
            ]

        for index in range(0, len(documents), batch_size):
            yield documents[index:index + batch_size]


class KnowledgeUnitRepository(_SQLiteRepository):
    """KnowledgeUnit repository."""

    def __init__(self, db_path: str = "data/news.db"):
        super().__init__(db_path)
        self._init_table()
        self._ensure_materialized_search_state()

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
                    entity_ids TEXT NOT NULL DEFAULT '[]',
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
            self._ensure_column(
                connection,
                "knowledge_units",
                "entity_ids",
                "TEXT NOT NULL DEFAULT '[]'",
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_units_doc_id ON knowledge_units(doc_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_units_cluster_id ON knowledge_units(cluster_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_units_unit_type ON knowledge_units(unit_type)"
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_units_fts USING fts5(
                    ku_id UNINDEXED,
                    summary,
                    unit_type,
                    source_name,
                    evidence_text,
                    entity_mentions,
                    entity_names,
                    tags
                )
                """
            )
            connection.commit()

    def _ensure_materialized_search_state(self) -> None:
        with self._connect() as connection:
            entity_ids_updated = self._backfill_entity_ids_from_payload(connection)
            self._backfill_fts_rows(connection)
            if entity_ids_updated:
                connection.commit()

    def _backfill_entity_ids_from_payload(self, connection: sqlite3.Connection) -> int:
        rows = connection.execute(
            """
            SELECT ku_id, payload
            FROM knowledge_units
            WHERE entity_ids = '[]'
            """
        ).fetchall()
        updates: list[tuple[str, str]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            entity_ids = list(
                dict.fromkeys(
                    entity.get("entity_id")
                    for entity in payload.get("entities", [])
                    if isinstance(entity, dict) and entity.get("entity_id")
                )
            )
            if not entity_ids:
                continue
            updates.append((json.dumps(entity_ids, ensure_ascii=False), row["ku_id"]))

        if updates:
            connection.executemany(
                "UPDATE knowledge_units SET entity_ids = ? WHERE ku_id = ?",
                updates,
            )
        return len(updates)

    def _backfill_fts_rows(self, connection: sqlite3.Connection) -> int:
        ku_count = connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
        if ku_count == 0:
            return 0

        fts_count = connection.execute("SELECT COUNT(*) FROM knowledge_units_fts").fetchone()[0]
        if fts_count == ku_count:
            return 0

        rows = connection.execute(
            "SELECT payload FROM knowledge_units ORDER BY published_at DESC, ku_id ASC"
        ).fetchall()
        units = [KnowledgeUnit.model_validate(json.loads(row["payload"])) for row in rows]
        connection.execute("DELETE FROM knowledge_units_fts")
        self._sync_fts_rows(connection, units)
        connection.commit()
        return len(units)

    def _ensure_column(
        self,
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
                json.dumps(
                    [entity.entity_id for entity in unit.entities if entity.entity_id],
                    ensure_ascii=False,
                ),
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
                    ku_id, doc_id, unit_kind, unit_type, summary, primary_mentions, entity_ids,
                    event_time, published_at, cluster_id, conflict_status, status, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ku_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    unit_kind = excluded.unit_kind,
                    unit_type = excluded.unit_type,
                    summary = excluded.summary,
                    primary_mentions = excluded.primary_mentions,
                    entity_ids = excluded.entity_ids,
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
            self._sync_fts_rows(connection, units)
            connection.commit()
        return len(units)

    def _sync_fts_rows(
        self,
        connection: sqlite3.Connection,
        units: Sequence[KnowledgeUnit],
    ) -> None:
        delete_rows = [(unit.ku_id,) for unit in units]
        if delete_rows:
            connection.executemany(
                "DELETE FROM knowledge_units_fts WHERE ku_id = ?",
                delete_rows,
            )
        insert_rows = []
        for unit in units:
            sections = build_knowledge_unit_search_sections(unit)
            insert_rows.append(
                (
                    unit.ku_id,
                    sections["summary"],
                    sections["unit_type"],
                    sections["source_name"],
                    sections["evidence_text"],
                    sections["entity_mentions"],
                    sections["entity_names"],
                    sections["tags"],
                )
            )
        if insert_rows:
            connection.executemany(
                """
                INSERT INTO knowledge_units_fts (
                    ku_id, summary, unit_type, source_name, evidence_text,
                    entity_mentions, entity_names, tags
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                insert_rows,
            )

    def get_all(self) -> list[KnowledgeUnit]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM knowledge_units ORDER BY published_at DESC, ku_id ASC"
            ).fetchall()
        return [KnowledgeUnit.model_validate(json.loads(row["payload"])) for row in rows]

    def get_by_ids(self, ku_ids: Sequence[str]) -> list[KnowledgeUnit]:
        if not ku_ids:
            return []
        placeholders = ", ".join("?" for _ in ku_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM knowledge_units WHERE ku_id IN ({placeholders})",
                list(ku_ids),
            ).fetchall()
        return [KnowledgeUnit.model_validate(json.loads(row["payload"])) for row in rows]

    def search_bm25(
        self,
        match_query: str,
        *,
        top_k: int,
        time_range: tuple[str, str] | None = None,
        event_types: Sequence[str] | None = None,
        entity_ids: Sequence[str] | None = None,
    ) -> list[tuple[str, float]]:
        if not match_query.strip():
            return []
        where_clauses = ["knowledge_units_fts MATCH ?"]
        params: list[Any] = [match_query]
        self._append_filter_clauses(
            where_clauses,
            params,
            alias="ku",
            time_range=time_range,
            event_types=event_types,
            entity_ids=entity_ids,
        )
        sql = f"""
            SELECT ku.ku_id, bm25(knowledge_units_fts) AS bm25_score
            FROM knowledge_units_fts
            JOIN knowledge_units AS ku ON ku.ku_id = knowledge_units_fts.ku_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY bm25_score ASC
            LIMIT ?
        """
        params.append(top_k)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [(row["ku_id"], float(row["bm25_score"])) for row in rows]

    def find_by_entity_ids(
        self,
        entity_ids: Sequence[str],
        *,
        time_range: tuple[str, str] | None = None,
        event_types: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[str]:
        """Return ku_ids for KUs associated with any of the given entity_ids.

        Uses json_each for precise matching instead of LIKE pattern matching.
        """
        if not entity_ids:
            return []
        placeholders = ", ".join("?" for _ in entity_ids)
        where_parts: list[str] = [
            f"je.value IN ({placeholders})"
        ]
        params: list[Any] = list(entity_ids)
        if time_range is not None:
            where_parts.append(
                "substr(COALESCE(ku.event_time, ku.published_at), 1, 10) BETWEEN ? AND ?"
            )
            params.extend(time_range)
        if event_types:
            type_placeholders = ", ".join("?" for _ in event_types)
            where_parts.append(f"ku.unit_type IN ({type_placeholders})")
            params.extend(event_types)
        params.append(limit)
        sql = f"""
            SELECT DISTINCT ku.ku_id
            FROM knowledge_units ku, json_each(ku.entity_ids) je
            WHERE {' AND '.join(where_parts)}
            ORDER BY ku.published_at DESC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [row["ku_id"] for row in rows]

    def find_by_time_range(
        self,
        time_range: tuple[str, str],
        *,
        limit: int = 100,
    ) -> list[str]:
        """Return ku_ids for KUs within the given time range.

        Used as fallback when no entities or search terms are available.
        """
        sql = """
            SELECT ku_id
            FROM knowledge_units
            WHERE substr(COALESCE(event_time, published_at), 1, 10) BETWEEN ? AND ?
            ORDER BY published_at DESC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, (*time_range, limit)).fetchall()
        return [row["ku_id"] for row in rows]

    def rebuild_fts_index(self) -> int:
        units = self.get_all()
        with self._connect() as connection:
            connection.execute("DELETE FROM knowledge_units_fts")
            self._sync_fts_rows(connection, units)
            connection.commit()
        return len(units)

    def _append_filter_clauses(
        self,
        where_clauses: list[str],
        params: list[Any],
        *,
        alias: str,
        time_range: tuple[str, str] | None = None,
        event_types: Sequence[str] | None = None,
        entity_ids: Sequence[str] | None = None,
        ku_ids: Sequence[str] | None = None,
    ) -> None:
        if time_range is not None:
            where_clauses.append(
                f"substr(COALESCE({alias}.event_time, {alias}.published_at), 1, 10) BETWEEN ? AND ?"
            )
            params.extend(time_range)
        if event_types:
            placeholders = ", ".join("?" for _ in event_types)
            where_clauses.append(f"{alias}.unit_type IN ({placeholders})")
            params.extend(event_types)
        if entity_ids:
            entity_conditions = [f"{alias}.entity_ids LIKE ?" for _ in entity_ids]
            where_clauses.append(f"({' OR '.join(entity_conditions)})")
            params.extend([f'%"{entity_id}"%' for entity_id in entity_ids])
        if ku_ids:
            placeholders = ", ".join("?" for _ in ku_ids)
            where_clauses.append(f"{alias}.ku_id IN ({placeholders})")
            params.extend(ku_ids)


class KnowledgeProcessingLogRepository(_SQLiteRepository):
    """Offline knowledge-processing log repository."""

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
