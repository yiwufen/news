"""CLI argument parsing and command dispatch tests."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.cli import cmd_ingest, cmd_search, main
from src.orchestration.result import GraphMeta, PipelineResult, RetrievalMeta
from src.schemas.query import IntentType


class TestCmdSearch:
    """Tests for the search subcommand."""

    def test_search_outputs_json_to_stdout(self, capsys, monkeypatch) -> None:
        fake_result = PipelineResult(
            request_id="test-1234",
            query=MagicMock(
                to_dict=lambda: {
                    "intent": "ENTITY_OVERVIEW",
                    "entities": ["小米集团"],
                    "time_range": None,
                    "filters": {},
                    "original_query": "小米集团",
                    "confidence": 1.0,
                }
            ),
            source="knowledge_base",
            knowledge_units=[{"ku_id": "ku_1"}],
            entities=[],
            event_clusters=[],
            total_count=1,
            retrieval=RetrievalMeta(retrieval_mode="bm25", bm25_count=1),
            graph=GraphMeta(),
            errors=[],
        )
        fake_result.graph_result = None

        monkeypatch.setattr("src.cli.run_pipeline", lambda **kwargs: fake_result)

        import argparse

        args = argparse.Namespace(
            entities=["小米集团"],
            time_range=None,
            event_types=None,
            intent=None,
            hops=None,
            target_entity=None,
            top_k=20,
            graph_enabled=True,
        )
        cmd_search(args)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["request_id"] == "test-1234"
        assert output["total_count"] == 1
        assert output["source"] == "knowledge_base"

    def test_search_passes_time_range(self, monkeypatch) -> None:
        captured_kwargs = {}

        def capture_run_pipeline(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(
                to_dict=lambda: {"request_id": "x", "query": {}, "source": "kb",
                                 "knowledge_units": [], "entities": [], "event_clusters": [],
                                 "total_count": 0, "retrieval": {}, "graph": {},
                                 "graph_data": {}, "errors": []},
            )

        monkeypatch.setattr("src.cli.run_pipeline", capture_run_pipeline)

        import argparse

        args = argparse.Namespace(
            entities=["小米集团"],
            time_range="2025-04-01:2026-04-13",
            event_types=None,
            intent=None,
            hops=None,
            target_entity=None,
            top_k=20,
            graph_enabled=True,
        )
        cmd_search(args)

        sq = captured_kwargs["structured_query"]
        assert sq.time_range is not None
        assert sq.time_range.start.isoformat() == "2025-04-01"
        assert sq.time_range.end.isoformat() == "2026-04-13"

    def test_search_passes_intent(self, monkeypatch) -> None:
        captured_kwargs = {}

        def capture_run_pipeline(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(
                to_dict=lambda: {"request_id": "x", "query": {}, "source": "kb",
                                 "knowledge_units": [], "entities": [], "event_clusters": [],
                                 "total_count": 0, "retrieval": {}, "graph": {},
                                 "graph_data": {}, "errors": []},
            )

        monkeypatch.setattr("src.cli.run_pipeline", capture_run_pipeline)

        import argparse

        args = argparse.Namespace(
            entities=["小米集团"],
            time_range=None,
            event_types=["investment"],
            intent="ENTITY_TIMELINE",
            hops=None,
            target_entity=None,
            top_k=50,
            graph_enabled=False,
        )
        cmd_search(args)

        sq = captured_kwargs["structured_query"]
        assert sq.intent == IntentType.ENTITY_TIMELINE
        assert sq.filters.event_types == ["investment"]
        assert captured_kwargs["top_k"] == 50
        assert captured_kwargs["graph_enabled"] is False


class TestCmdIngest:
    """Tests for the ingest subcommand."""

    def test_ingest_outputs_summary_json(self, capsys, monkeypatch) -> None:
        from src.pipeline.continuous import ContinuousRunResult

        fake_result = ContinuousRunResult(
            nodes_created=5,
            edges_created=3,
            errors=[],
            knowledge_units_extracted=10,
            knowledge_units_saved=10,
            entities_saved=4,
            clusters_saved=3,
        )

        monkeypatch.setattr("src.cli.run_continuous", lambda **kwargs: fake_result)

        import argparse

        args = argparse.Namespace(
            batch_size=10,
            graph_enabled=True,
            incremental=True,
            dry_run=False,
        )
        cmd_ingest(args)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["knowledge_units_extracted"] == 10
        assert output["nodes_created"] == 5


class TestMainArgparse:
    """Tests for the main argparse entry point."""

    def test_search_subcommand_dispatches(self, monkeypatch) -> None:
        calls = []

        def fake_cmd_search(args):
            calls.append("search")

        monkeypatch.setattr("src.cli.cmd_search", fake_cmd_search)
        monkeypatch.setattr(sys, "argv", ["knowledge-cli", "search", "--entities", "小米"])

        main()
        assert calls == ["search"]

    def test_ingest_subcommand_dispatches(self, monkeypatch) -> None:
        calls = []

        def fake_cmd_ingest(args):
            calls.append("ingest")

        monkeypatch.setattr("src.cli.cmd_ingest", fake_cmd_ingest)
        monkeypatch.setattr(sys, "argv", ["knowledge-cli", "ingest"])

        main()
        assert calls == ["ingest"]

    def test_no_subcommand_exits(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["knowledge-cli"])
        with pytest.raises(SystemExit):
            main()
