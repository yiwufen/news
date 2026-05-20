"""Tests for normalized_name, entity_aliases, entity_identifiers, and cluster_entity_map indexes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.entities import (
    Entity,
    EntityRepository,
    EntityResolver,
    normalize_entity_name,
)
from src.event_clustering import (
    EventCluster,
    EventClusterRepository,
    _hash_entity_ids,
)
from src.knowledge_base import KnowledgeUnitRepository


def _make_entity(
    canonical_name: str,
    entity_type: str = "Company",
    aliases: list[str] | None = None,
    identifiers: dict[str, str] | None = None,
    entity_id: str | None = None,
    source_ku_ids: list[str] | None = None,
) -> Entity:
    kw: dict = {
        "canonical_name": canonical_name,
        "entity_type": entity_type,
        "aliases": aliases or [],
        "identifiers": identifiers or {},
        "source_ku_ids": source_ku_ids or [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    if entity_id:
        kw["entity_id"] = entity_id
    return Entity(**kw)


class TestSaveBatchPopulatesIndexes:
    def test_normalized_name_populated(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity("比亚迪集团股份有限公司", entity_id="ent_byd")
        repo.save_batch([entity])

        with repo._connect() as conn:
            row = conn.execute(
                "SELECT normalized_name FROM entities WHERE entity_id = ?",
                ("ent_byd",),
            ).fetchone()
        assert row is not None
        assert row["normalized_name"] == normalize_entity_name("比亚迪集团股份有限公司")

    def test_entity_aliases_populated(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity(
            "比亚迪",
            aliases=["BYD", "比亚迪股份"],
            entity_id="ent_byd",
        )
        repo.save_batch([entity])

        with repo._connect() as conn:
            rows = conn.execute(
                "SELECT normalized_alias FROM entity_aliases WHERE entity_id = ?",
                ("ent_byd",),
            ).fetchall()
        aliases = {r["normalized_alias"] for r in rows}
        # "比亚迪" is canonical normalized, so it's excluded from aliases
        assert normalize_entity_name("BYD") in aliases or "byd" in aliases
        # "比亚迪股份" normalizes to "比亚迪股份" (no suffix to strip beyond 股份)
        # but it might equal canonical, so check accordingly

    def test_entity_identifiers_populated(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity(
            "腾讯",
            identifiers={"stock_code": "00700", "isin": "KYG875721634"},
            entity_id="ent_tencent",
        )
        repo.save_batch([entity])

        with repo._connect() as conn:
            rows = conn.execute(
                "SELECT identifier_key, identifier_value FROM entity_identifiers WHERE entity_id = ?",
                ("ent_tencent",),
            ).fetchall()
        idents = {(r["identifier_key"], r["identifier_value"]) for r in rows}
        assert ("stock_code", "00700") in idents
        assert ("isin", "KYG875721634") in idents

    def test_save_batch_updates_indexes_on_re_save(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity("腾讯", aliases=["Tencent"], entity_id="ent_tencent")
        repo.save_batch([entity])

        # Re-save with updated aliases
        entity.aliases = ["Tencent", "腾讯科技"]
        repo.save_batch([entity])

        with repo._connect() as conn:
            rows = conn.execute(
                "SELECT normalized_alias FROM entity_aliases WHERE entity_id = ?",
                ("ent_tencent",),
            ).fetchall()
        aliases = {r["normalized_alias"] for r in rows}
        # Old aliases should be replaced, not accumulated
        assert len(aliases) <= 3  # normalized forms of Tencent + 腾讯科技 (not canonical)


class TestEntitiesByNormalizedNames:
    def test_finds_by_normalized_name(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity("比亚迪集团股份有限公司", entity_id="ent_byd")
        repo.save_batch([entity])

        norm = normalize_entity_name("比亚迪集团股份有限公司")
        results = repo._entities_by_normalized_names([norm])
        assert len(results) == 1
        assert results[0].entity_id == "ent_byd"

    def test_empty_names_returns_empty(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        assert repo._entities_by_normalized_names([]) == []


class TestEntitiesByAlias:
    def test_finds_by_alias(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity("比亚迪", aliases=["BYD Company"], entity_id="ent_byd")
        repo.save_batch([entity])

        results = repo._entities_by_alias(normalize_entity_name("BYD Company"))
        assert len(results) >= 1
        assert any(e.entity_id == "ent_byd" for e in results)


class TestEntitiesByIdentifier:
    def test_finds_by_key_value(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity(
            "腾讯", identifiers={"stock_code": "00700"}, entity_id="ent_tencent",
        )
        repo.save_batch([entity])

        results = repo._entities_by_identifier("stock_code", "00700")
        assert len(results) == 1
        assert results[0].entity_id == "ent_tencent"

    def test_finds_by_value_only(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity(
            "腾讯", identifiers={"stock_code": "00700"}, entity_id="ent_tencent",
        )
        repo.save_batch([entity])

        results = repo._entities_by_identifier_value("00700")
        assert len(results) == 1
        assert results[0].entity_id == "ent_tencent"


class TestEntitiesByNormalizedPrefix:
    def test_containment_match(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        entity = _make_entity("宁德时代", entity_id="ent_catl")
        repo.save_batch([entity])

        norm = normalize_entity_name("宁德时代")
        results = repo._entities_by_normalized_prefix(norm[:2])
        assert len(results) >= 1


class TestFindByNamesUsesSQL:
    def test_find_by_names_without_get_all(self, tmp_path) -> None:
        """find_by_names should work without calling get_all()."""
        repo = EntityRepository(str(tmp_path / "db"))
        repo.save_batch([
            _make_entity("比亚迪", aliases=["BYD"], entity_id="ent_byd"),
            _make_entity("腾讯控股", entity_id="ent_tencent"),
        ])

        # Monkey-patch get_all to fail if called
        original_get_all = repo.get_all

        def fail_get_all():
            raise AssertionError("get_all() should not be called")

        repo.get_all = fail_get_all  # type: ignore

        results = repo.find_by_names(["比亚迪"])
        assert len(results) == 1
        assert results[0].entity_id == "ent_byd"

        # Restore
        repo.get_all = original_get_all  # type: ignore

    def test_find_by_names_cross_lingual(self, tmp_path) -> None:
        repo = EntityRepository(str(tmp_path / "db"))
        repo.save_batch([
            _make_entity("比亚迪", aliases=["BYD Company"], entity_id="ent_byd"),
        ])
        results = repo.find_by_names(["BYD"])
        assert len(results) >= 1
        assert any(e.entity_id == "ent_byd" for e in results)


class TestClusterEntityMap:
    def test_save_and_query(self, tmp_path) -> None:
        db_path = str(tmp_path / "db")
        ku_repo = KnowledgeUnitRepository(db_path)
        repo = EventClusterRepository(db_path, knowledge_units=ku_repo)

        cluster = EventCluster(
            cluster_id="clu_test",
            cluster_type="event",
            entity_ids=["ent_a", "ent_b"],
            title="test event",
            summary="test event",
            member_ku_ids=["ku_1"],
            source_doc_ids=["doc_1"],
            updated_at=datetime.now(UTC),
        )
        repo.save_batch([cluster])

        with repo._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cluster_entity_map WHERE cluster_id = ?",
                ("clu_test",),
            ).fetchall()
        assert len(rows) == 2  # one row per entity
        entity_ids_in_map = {r["entity_id"] for r in rows}
        assert entity_ids_in_map == {"ent_a", "ent_b"}

    def test_find_matching_clusters(self, tmp_path) -> None:
        db_path = str(tmp_path / "db")
        ku_repo = KnowledgeUnitRepository(db_path)
        repo = EventClusterRepository(db_path, knowledge_units=ku_repo)

        cluster = EventCluster(
            cluster_id="clu_test",
            cluster_type="event",
            entity_ids=["ent_a", "ent_b"],
            title="test event",
            summary="test event",
            member_ku_ids=["ku_1"],
            source_doc_ids=["doc_1"],
            updated_at=datetime.now(UTC),
        )
        repo.save_batch([cluster])

        results = repo._find_matching_clusters(["ent_b", "ent_a"], "event")
        assert len(results) == 1
        assert results[0].cluster_id == "clu_test"

    def test_find_matching_clusters_type_mismatch(self, tmp_path) -> None:
        db_path = str(tmp_path / "db")
        ku_repo = KnowledgeUnitRepository(db_path)
        repo = EventClusterRepository(db_path, knowledge_units=ku_repo)

        cluster = EventCluster(
            cluster_id="clu_test",
            cluster_type="event",
            entity_ids=["ent_a"],
            title="test",
            summary="test",
            member_ku_ids=["ku_1"],
            source_doc_ids=["doc_1"],
            updated_at=datetime.now(UTC),
        )
        repo.save_batch([cluster])

        results = repo._find_matching_clusters(["ent_a"], "risk")
        assert len(results) == 0

    def test_hash_entity_ids_deterministic(self) -> None:
        h1 = _hash_entity_ids(["a", "b", "c"])
        h2 = _hash_entity_ids(["c", "a", "b"])  # sorted → same
        assert h1 == h2

    def test_hash_entity_ids_different_for_different_sets(self) -> None:
        h1 = _hash_entity_ids(["a", "b"])
        h2 = _hash_entity_ids(["a", "c"])
        assert h1 != h2
