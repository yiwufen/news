"""Role-aware container healthcheck (docker/healthcheck.py).

The healthcheck distinguishes the long-lived MCP server (PID 1 is
``src.cli serve``) from the ingestion/fetch loop containers. A crash-looping
server must report unhealthy even when the shared data volume carries fresh
loop logs from other containers.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "docker" / "healthcheck.py"


def _load_healthcheck(monkeypatch: pytest.MonkeyPatch, cmdline: bytes | None) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("healthcheck_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fake_open(path: str, mode: str = "r"):
        if path == "/proc/1/cmdline":
            if cmdline is None:
                raise OSError("no such file")
            class _FakeCmdline:
                def __enter__(self):
                    return self
                def __exit__(self, *args: object) -> None:
                    return None
                def read(self) -> bytes:
                    assert cmdline is not None
                    return cmdline
            return _FakeCmdline()
        raise OSError(f"unexpected path: {path}")

    monkeypatch.setattr("builtins.open", fake_open)
    return module


def test_server_role_detected_by_serve_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_healthcheck(
        monkeypatch,
        b"python\0-m\0src.cli\0serve\0--host\00.0.0.0\0--port\08000\0",
    )
    assert module._is_server_role() is True


def test_loop_roles_are_not_server(monkeypatch: pytest.MonkeyPatch) -> None:
    for cmdline in (b"python\0-m\0src.cli\0_run_offline\0", b"python\0-m\0src.cli\0_run_fetch\0"):
        module = _load_healthcheck(monkeypatch, cmdline)
        assert module._is_server_role() is False


def test_unreadable_cmdline_is_not_server(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_healthcheck(monkeypatch, None)
    assert module._is_server_role() is False


def test_server_role_requires_port_even_with_fresh_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_healthcheck(monkeypatch, b"python\0-m\0src.cli\0serve\0")
    monkeypatch.setattr(module, "_port_open", lambda port: False)
    monkeypatch.setattr(module, "_any_log_fresh", lambda paths, max_age: True)
    # Regression: fresh logs from sibling loop containers must not mask a
    # dead server.
    assert module.main() == 1


def test_server_role_healthy_when_port_open(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_healthcheck(monkeypatch, b"python\0-m\0src.cli\0serve\0")
    monkeypatch.setattr(module, "_port_open", lambda port: True)
    assert module.main() == 0


def test_loop_role_falls_back_to_fresh_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_healthcheck(monkeypatch, b"python\0-m\0src.cli\0_run_offline\0")
    monkeypatch.setattr(module, "_port_open", lambda port: False)
    monkeypatch.setattr(module, "_any_log_fresh", lambda paths, max_age: True)
    assert module.main() == 0


def test_loop_role_unhealthy_when_nothing_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_healthcheck(monkeypatch, b"python\0-m\0src.cli\0_run_fetch\0")
    monkeypatch.setattr(module, "_port_open", lambda port: False)
    monkeypatch.setattr(module, "_any_log_fresh", lambda paths, max_age: False)
    assert module.main() == 1
