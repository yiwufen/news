"""CLI argument parsing and command dispatch tests."""

from __future__ import annotations

import argparse
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.cli import cmd_ingest, cmd_search, cmd_start, cmd_stop, cmd_status, main
from src.orchestration.result import GraphMeta, PipelineResult, RetrievalMeta
from src.paths import DEFAULT_DB_PATH
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
            db=DEFAULT_DB_PATH,
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
            db=DEFAULT_DB_PATH,
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
            db=DEFAULT_DB_PATH,
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
            db="data/news.db",
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

    def test_start_subcommand_dispatches(self, monkeypatch) -> None:
        calls = []

        def fake_cmd_start(args):
            calls.append("start")

        monkeypatch.setattr("src.cli.cmd_start", fake_cmd_start)
        monkeypatch.setattr(sys, "argv", ["knowledge-cli", "start"])

        main()
        assert calls == ["start"]

    def test_stop_subcommand_dispatches(self, monkeypatch) -> None:
        calls = []

        def fake_cmd_stop(args):
            calls.append("stop")

        monkeypatch.setattr("src.cli.cmd_stop", fake_cmd_stop)
        monkeypatch.setattr(sys, "argv", ["knowledge-cli", "stop"])

        main()
        assert calls == ["stop"]

    def test_status_subcommand_dispatches(self, monkeypatch) -> None:
        calls = []

        def fake_cmd_status(args):
            calls.append("status")

        monkeypatch.setattr("src.cli.cmd_status", fake_cmd_status)
        monkeypatch.setattr(sys, "argv", ["knowledge-cli", "status"])

        main()
        assert calls == ["status"]


class TestCmdStart:
    """Tests for the start subcommand."""

    def test_start_spawns_both_services(self, monkeypatch) -> None:
        spawned = []
        pids_written = []

        def fake_spawn(command):
            pid = len(spawned) + 1000
            spawned.append(command)
            return pid

        def fake_write_pid(service, pid, command):
            pids_written.append((service, pid))

        monkeypatch.setattr("src.cli.read_pid", lambda s: None)
        monkeypatch.setattr("src.cli.spawn_process", fake_spawn)
        monkeypatch.setattr("src.cli.write_pid", fake_write_pid)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        args = argparse.Namespace(
            fetch_limit=100,
            fetch_interval=900,
            process_batch_size=10,
            process_interval=300,
            db="data/news.db",
            graph_enabled=True,
            time_window="",
            fetch_only=False,
            offline_only=False,
        )
        cmd_start(args)

        assert len(spawned) == 2
        assert ("fetch", 1000) in pids_written
        assert ("offline", 1001) in pids_written

    def test_start_skips_already_running(self, monkeypatch) -> None:
        spawned = []

        monkeypatch.setattr("src.cli.read_pid", lambda s: {"pid": 999, "started_at": "t"} if s == "fetch" else None)
        monkeypatch.setattr("src.cli.is_process_alive", lambda pid: True)
        monkeypatch.setattr("src.cli.spawn_process", lambda cmd: spawned.append(cmd) or 1000)
        monkeypatch.setattr("src.cli.write_pid", lambda *a: None)
        monkeypatch.setattr("src.cli.remove_pid", lambda s: None)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        args = argparse.Namespace(
            fetch_limit=100, fetch_interval=900,
            process_batch_size=10, process_interval=300,
            db="data/news.db", graph_enabled=False, time_window="",
            fetch_only=False, offline_only=False,
        )
        cmd_start(args)

        # fetch skipped, offline spawned
        assert len(spawned) == 1

    def test_start_fetch_only(self, monkeypatch) -> None:
        spawned = []

        monkeypatch.setattr("src.cli.read_pid", lambda s: None)
        monkeypatch.setattr("src.cli.spawn_process", lambda cmd: spawned.append(cmd) or 1000)
        monkeypatch.setattr("src.cli.write_pid", lambda *a: None)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        args = argparse.Namespace(
            fetch_limit=100, fetch_interval=900,
            process_batch_size=10, process_interval=300,
            db="data/news.db", graph_enabled=False, time_window="",
            fetch_only=True, offline_only=False,
        )
        cmd_start(args)
        assert len(spawned) == 1
        assert "_run_fetch" in spawned[0][-1] or any("_run_fetch" in a for a in spawned[0])

    def test_start_offline_only(self, monkeypatch) -> None:
        spawned = []

        monkeypatch.setattr("src.cli.read_pid", lambda s: None)
        monkeypatch.setattr("src.cli.spawn_process", lambda cmd: spawned.append(cmd) or 1000)
        monkeypatch.setattr("src.cli.write_pid", lambda *a: None)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        args = argparse.Namespace(
            fetch_limit=100, fetch_interval=900,
            process_batch_size=10, process_interval=300,
            db="data/news.db", graph_enabled=False, time_window="",
            fetch_only=False, offline_only=True,
        )
        cmd_start(args)
        assert len(spawned) == 1
        assert "_run_offline" in spawned[0][-1] or any("_run_offline" in a for a in spawned[0])
    """Tests for the stop subcommand."""

    def test_stop_terminates_running_process(self, monkeypatch) -> None:
        monkeypatch.setattr("src.cli.read_pid", lambda s: {"pid": 1234, "started_at": "t"})
        monkeypatch.setattr("src.cli.is_process_alive", lambda pid: True)

        stopped = []
        removed = []
        monkeypatch.setattr("src.cli.stop_process", lambda pid: stopped.append(pid))
        monkeypatch.setattr("src.cli.remove_pid", lambda s: removed.append(s))

        args = argparse.Namespace(fetch=False, offline=False)
        cmd_stop(args)

        assert 1234 in stopped
        assert "fetch" in removed
        assert "offline" in removed

    def test_stop_handles_not_running(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("src.cli.read_pid", lambda s: None)
        args = argparse.Namespace(fetch=False, offline=False)
        cmd_stop(args)

        captured = capsys.readouterr()
        assert "not running" in captured.out


class TestCmdStatus:
    """Tests for the status subcommand."""

    def test_status_reports_running(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("src.cli.read_pid",
                            lambda s: {"pid": 1234, "started_at": "2026-04-19T12:00:00"} if s == "fetch" else None)
        monkeypatch.setattr("src.cli.is_process_alive", lambda pid: True)

        args = argparse.Namespace()
        cmd_status(args)

        captured = capsys.readouterr()
        assert "running" in captured.out
        assert "1234" in captured.out

    def test_status_reports_not_running(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("src.cli.read_pid", lambda s: None)
        args = argparse.Namespace()
        cmd_status(args)

        captured = capsys.readouterr()
        assert "not running" in captured.out
