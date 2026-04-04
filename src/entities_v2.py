"""
标准实体模型、仓储与归一服务。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from src.knowledge_base import KnowledgeUnit


EntityKind = Literal["Company", "Organization", "Person", "Product", "Asset"]
ENTITY_KINDS: tuple[EntityKind, ...] = (
    "Company",
    "Organization",
    "Person",
    "Product",
    "Asset",
)


class Entity(BaseModel):
    """标准化实体。"""

    entity_id: str = Field(default_factory=lambda: f"ent_{uuid4().hex[:12]}")
    entity_type: EntityKind
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_ku_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def _normalize_name(name: str) -> str:
    normalized = re.sub(r"[\s()（）,，.。\-_/]+", "", name).lower()
    normalized = re.sub(r"(股份有限公司|有限责任公司|有限公司)$", "", normalized)
    return normalized


def _infer_entity_type(name: str) -> EntityKind:
    if re.search(r"(先生|女士|总裁|董事长|CEO|创始人)$", name):
        return "Person"
    if re.search(r"(产品|计划|基金|债券)$", name):
        return "Product"
    if re.search(r"(资产|地块|厂房|专利)$", name):
        return "Asset"
    if re.search(r"(协会|机构|研究院|部门|政府)$", name):
        return "Organization"
    return "Company"


def _resolve_entity_type(entity_type: str | None, mention: str) -> EntityKind:
    candidate = entity_type or _infer_entity_type(mention)
    if candidate in ENTITY_KINDS:
        return cast(EntityKind, candidate)
    return _infer_entity_type(mention)


class EntityRepository:
    """实体 SQLite 仓储。"""

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
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    primary_identifier TEXT,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name)"
            )
            connection.commit()

    def save_batch(self, entities: list[Entity]) -> int:
        if not entities:
            return 0
        rows = [
            (
                entity.entity_id,
                entity.canonical_name,
                entity.entity_type,
                next(iter(entity.identifiers.values()), None),
                entity.updated_at.isoformat(),
                json.dumps(entity.model_dump(mode="json"), ensure_ascii=False),
            )
            for entity in entities
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO entities (
                    entity_id, canonical_name, entity_type, primary_identifier, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    entity_type = excluded.entity_type,
                    primary_identifier = excluded.primary_identifier,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                rows,
            )
            connection.commit()
        return len(entities)

    def get_all(self) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM entities ORDER BY updated_at DESC, entity_id ASC"
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]


class EntityResolver:
    """保守实体归一。"""

    def __init__(self, repository: EntityRepository):
        self.repository = repository

    def resolve_units(
        self,
        units: list[KnowledgeUnit],
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[Entity]]:
        now = datetime.now(UTC)
        entities = {entity.entity_id: entity for entity in self.repository.get_all()}
        touched_entities: dict[str, Entity] = {}

        for unit in units:
            for entity_ref in unit.entities:
                matched = self._find_match(entity_ref.mention, entity_ref.identifiers, entities.values())
                if matched is None:
                    matched = Entity(
                        entity_type=_resolve_entity_type(entity_ref.entity_type, entity_ref.mention),
                        canonical_name=entity_ref.mention,
                        aliases=[entity_ref.mention],
                        identifiers=dict(entity_ref.identifiers),
                        source_ku_ids=[unit.ku_id],
                        created_at=now,
                        updated_at=now,
                    )
                    entities[matched.entity_id] = matched
                else:
                    if entity_ref.mention not in matched.aliases:
                        matched.aliases.append(entity_ref.mention)
                    if unit.ku_id not in matched.source_ku_ids:
                        matched.source_ku_ids.append(unit.ku_id)
                    matched.identifiers.update(entity_ref.identifiers)
                    matched.updated_at = now
                entity_ref.entity_id = matched.entity_id
                entity_ref.entity_type = matched.entity_type
                touched_entities[matched.entity_id] = matched

        resolved_entities = list(touched_entities.values())
        if persist:
            self.repository.save_batch(resolved_entities)
        return units, resolved_entities

    def _find_match(
        self,
        mention: str,
        identifiers: dict[str, str],
        existing_entities: Iterable[Entity],
    ) -> Entity | None:
        normalized = _normalize_name(mention)
        for entity in existing_entities:
            if identifiers and entity.identifiers:
                for key, value in identifiers.items():
                    if entity.identifiers.get(key) == value:
                        return entity

            if normalized == _normalize_name(entity.canonical_name):
                return entity

            alias_match = next(
                (alias for alias in entity.aliases if _normalize_name(alias) == normalized),
                None,
            )
            if alias_match:
                return entity

            similarity = SequenceMatcher(None, normalized, _normalize_name(entity.canonical_name)).ratio()
            if similarity >= 0.95 and entity.entity_type == _infer_entity_type(mention):
                return entity
        return None
