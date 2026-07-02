"""Tests for src.process_manager: PID file management and process liveness."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_IS_WINDOWS = sys.platform == "win32"

from src.process_manager import (
    PID_DIR,
    read_pid,
    remove_pid,
    write_pid,
    is_process_alive,
    spawn_process,
    stop_process,
)


class TestPidFileIO:
    """PID file read/write/remove operations."""

    def test_write_and_read_pid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.process_manager.PID_DIR", tmp_path)
        write_pid("fetch", 12345, ["python", "-m", "src.cli", "_run_fetch"])
        result = read_pid("fetch")
        assert result is not None
        assert result["pid"] == 12345
        assert result["command"] == ["python", "-m", "src.cli", "_run_fetch"]
        assert "started_at" in result

    def test_read_pid_returns_none_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.process_manager.PID_DIR", tmp_path)
        assert read_pid("fetch") is None

    def test_read_pid_returns_none_on_corrupt_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.process_manager.PID_DIR", tmp_path)
        (tmp_path / "fetch.json").write_text("not json", encoding="utf-8")
        assert read_pid("fetch") is None

    def test_remove_pid_deletes_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.process_manager.PID_DIR", tmp_path)
        write_pid("fetch", 12345, [])
        assert read_pid("fetch") is not None
        remove_pid("fetch")
        assert read_pid("fetch") is None

    def test_remove_pid_noop_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.process_manager.PID_DIR", tmp_path)
        remove_pid("nonexistent")  # should not raise

    def test_write_pid_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        nested = tmp_path / "deep" / ".pids"
        monkeypatch.setattr("src.process_manager.PID_DIR", nested)
        write_pid("fetch", 999, [])
        assert (nested / "fetch.json").exists()


class TestIsProcessAlive:
    """Process liveness check via Windows ctypes."""

    def test_current_process_is_alive(self) -> None:
        import os
        assert is_process_alive(os.getpid()) is True

    def test_nonexistent_pid_is_dead(self) -> None:
        # PID 0 is System Idle Process on Windows, but OpenProcess with
        # PROCESS_QUERY_LIMITED_INFORMATION typically fails for it.
        # Use a very large PID that is guaranteed not to exist.
        assert is_process_alive(999999999) is False


class TestSpawnStopProcess:
    """Subprocess spawn and stop."""

    @pytest.mark.skipif(not _IS_WINDOWS, reason="creationflags (CREATE_NO_WINDOW) is Windows-only")
    def test_spawn_process_calls_popen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_popen = MagicMock(return_value=mock_proc)
        monkeypatch.setattr("src.process_manager.subprocess.Popen", mock_popen)
        pid = spawn_process(["python", "-m", "src.cli", "_run_fetch", "--limit", "100"])
        assert pid == 54321
        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("creationflags") == 0x08000000

    @pytest.mark.skipif(not _IS_WINDOWS, reason="taskkill is Windows-only; Linux uses os.kill")
    def test_stop_process_calls_taskkill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_run = MagicMock()
        monkeypatch.setattr("src.process_manager.subprocess.run", mock_run)
        stop_process(12345)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "taskkill" in args
        assert "12345" in args
