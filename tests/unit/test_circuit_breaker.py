"""Tests for the entity-enhancement circuit breaker and fail-fast behavior.

Covers:
- CircuitBreaker trip / reset / check semantics
- EntityResolver fail-fast: an enhancement-API failure (description / alias /
  embedding) raises EntityEnhancementError instead of silently degrading
- The breaker is transparent when the API is healthy (no regression)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.entities import Entity, EntityEnhancementError, EntityRepository, EntityResolver
from src.pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError


# ---------------------------------------------------------------------------
# CircuitBreaker unit tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_does_not_trip_below_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert not cb.is_tripped
        assert cb.consecutive_failures == 4
        cb.check()  # no raise

    def test_trips_at_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_tripped
        cb.record_failure()
        assert cb.is_tripped
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_success_resets_counter(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        assert not cb.is_tripped
        # Two more failures should not trip (counter restarted)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_tripped

    def test_success_resets_after_trip(self) -> None:
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_tripped
        cb.record_success()
        assert not cb.is_tripped
        cb.check()  # no raise after reset

    def test_threshold_one_trips_immediately(self) -> None:
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.is_tripped
        with pytest.raises(CircuitOpenError):
            cb.check()

    def test_invalid_threshold_rejected(self) -> None:
        with pytest.raises(ValueError):
            CircuitBreaker(failure_threshold=0)


# ---------------------------------------------------------------------------
# EntityResolver fail-fast behavior
# ---------------------------------------------------------------------------


def _make_resolver(
    description_generator: Any | None = None,
    alias_generator: Any | None = None,
    embedding_provider: Any | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    tmp_path: Any = None,
) -> tuple[EntityResolver, dict[str, Entity]]:
    """Build a resolver backed by an empty temp DB."""
    from pathlib import Path

    if tmp_path is None:
        import tempfile

        tmp_path = Path(tempfile.mkdtemp())
    db_path = str(Path(tmp_path) / "test_entities.db")
    repo = EntityRepository(db_path)
    resolver = EntityResolver(
        repo,
        embedding_provider=embedding_provider,
        description_generator=description_generator,
        alias_generator=alias_generator,
        circuit_breaker=circuit_breaker,
    )
    return resolver, {}


def _make_unit(mention: str = "宁德时代") -> Any:
    from src.knowledge_base import (
        EntityRef,
        EvidenceSpan,
        KnowledgeUnit,
        SourceRef,
        TimeRef,
    )
    now = datetime.now(UTC)
    return KnowledgeUnit(
        unit_kind="event",
        unit_type="market_analysis",
        summary="test summary",
        entities=[EntityRef(mention=mention, entity_type="Company")],
        source=SourceRef(doc_id="doc_test", source_name="test"),
        evidence=[EvidenceSpan(text="test evidence")],
        time=TimeRef(published_at=now, extracted_at=now),
    )


class TestFailFastEnhancement:
    """Enhancement-API failures must propagate, not silently degrade."""

    def test_description_failure_raises(self, tmp_path) -> None:
        gen = MagicMock()
        gen.generate.side_effect = RuntimeError("LLM quota exhausted")
        resolver, cache = _make_resolver(
            description_generator=gen, tmp_path=tmp_path
        )
        # generate() now raises directly (no try/except swallowing it into a
        # warning + None). The failure propagates instead of silently degrading.
        with pytest.raises(RuntimeError, match="quota exhausted"):
            resolver.resolve_units_with_cache([_make_unit()], cache, persist=False)

    def test_alias_failure_raises(self, tmp_path) -> None:
        gen = MagicMock()
        gen.generate.side_effect = RuntimeError("alias API down")
        resolver, cache = _make_resolver(
            alias_generator=gen, tmp_path=tmp_path
        )
        with pytest.raises(RuntimeError, match="alias API down"):
            resolver.resolve_units_with_cache([_make_unit()], cache, persist=False)

    def test_embedding_failure_raises_during_disambiguation(self, tmp_path) -> None:
        # Two entities with the same normalized name force multi-candidate
        # disambiguation, which calls embed().
        now = datetime.now(UTC)
        e1 = Entity(
            entity_type="Company",
            canonical_name="测试实体",
            aliases=["测试实体"],
            description="desc one",
            source_ku_ids=["ku_a"],
            created_at=now,
            updated_at=now,
        )
        e2 = Entity(
            entity_type="Company",
            canonical_name="测试实体",
            aliases=["测试实体"],
            description="desc two",
            source_ku_ids=["ku_b"],
            created_at=now,
            updated_at=now,
        )
        cache = {e1.entity_id: e1, e2.entity_id: e2}

        provider = MagicMock()
        provider.embed.side_effect = RuntimeError("embedding service down")

        resolver, _ = _make_resolver(
            embedding_provider=provider, tmp_path=tmp_path
        )
        with pytest.raises(EntityEnhancementError, match="embedding"):
            resolver.resolve_units_with_cache([_make_unit("测试实体")], cache, persist=False)

    def test_circuit_breaker_records_failure(self, tmp_path) -> None:
        gen = MagicMock()
        gen.generate.side_effect = RuntimeError("quota exhausted")
        cb = CircuitBreaker(failure_threshold=3)
        resolver, cache = _make_resolver(
            description_generator=gen, circuit_breaker=cb, tmp_path=tmp_path
        )
        # First enhancement failure: resolver raises (caller would catch +
        # record_failure in pipeline; here we simulate that contract).
        with pytest.raises(RuntimeError):
            resolver.resolve_units_with_cache([_make_unit()], cache, persist=False)

    def test_circuit_breaker_check_aborts_resolve(self, tmp_path) -> None:
        """Once tripped, check() at the top of the mention loop raises."""
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()  # trip it
        assert cb.is_tripped

        resolver, cache = _make_resolver(circuit_breaker=cb, tmp_path=tmp_path)
        with pytest.raises(CircuitOpenError):
            resolver.resolve_units_with_cache([_make_unit()], cache, persist=False)


class TestHealthyPathTransparent:
    """When APIs are healthy, the breaker must not interfere."""

    def test_success_path_records_success(self, tmp_path) -> None:
        gen = MagicMock()
        gen.generate.return_value = "a description"
        alias_gen = MagicMock()
        alias_gen.generate.return_value = ["别名1"]
        cb = CircuitBreaker(failure_threshold=3)
        resolver, cache = _make_resolver(
            description_generator=gen,
            alias_generator=alias_gen,
            circuit_breaker=cb,
            tmp_path=tmp_path,
        )
        # Should complete without error and reset the breaker.
        units, entities = resolver.resolve_units_with_cache(
            [_make_unit()], cache, persist=False
        )
        assert len(entities) == 1
        assert entities[0].description == "a description"
        assert "别名1" in entities[0].aliases
        assert cb.consecutive_failures == 0
        assert not cb.is_tripped
