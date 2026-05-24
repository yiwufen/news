"""Process lifecycle management for fetch and offline services.

Uses PID files in ``data/.pids/`` to track running child processes.
Supports Windows (ctypes/taskkill) and Linux/MacOS (kill/ps).
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = REPO_ROOT / "data" / ".pids"
SERVICES = ("fetch", "offline")

_IS_WINDOWS = sys.platform == "win32"

CREATE_NO_WINDOW = 0x08000000 if _IS_WINDOWS else 0


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

if _IS_WINDOWS:
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259
    _kernel32 = ctypes.windll.kernel32

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

else:
    def is_process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Spawn / stop
# ---------------------------------------------------------------------------

def spawn_process(command: list[str]) -> int:
    kwargs: dict = dict(
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if _IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.Popen(command, **kwargs)
    return proc.pid


if _IS_WINDOWS:
    def stop_process(pid: int) -> None:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            check=False,
        )
else:
    def stop_process(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
