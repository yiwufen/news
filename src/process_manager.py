"""Process lifecycle management for fetch and offline services.

Uses PID files in ``data/.pids/`` to track running child processes.
Windows-only: relies on ``ctypes`` for liveness checks and ``taskkill`` for termination.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from ctypes import wintypes

REPO_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = REPO_ROOT / "data" / ".pids"
SERVICES = ("fetch", "offline")

CREATE_NO_WINDOW = 0x08000000

# Windows ctypes constants for process liveness check
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_kernel32 = ctypes.windll.kernel32


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def _ensure_pid_dir() -> Path:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    return PID_DIR


def read_pid(service: str) -> dict | None:
    path = PID_DIR / f"{service}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_pid(service: str, pid: int, command: list[str]) -> None:
    _ensure_pid_dir()
    path = PID_DIR / f"{service}.json"
    data = {
        "pid": pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_pid(service: str) -> None:
    path = PID_DIR / f"{service}.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Process liveness
# ---------------------------------------------------------------------------

def is_process_alive(pid: int) -> bool:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return exit_code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Spawn / stop
# ---------------------------------------------------------------------------

def spawn_process(command: list[str]) -> int:
    proc = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    return proc.pid


def stop_process(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        check=False,
    )
