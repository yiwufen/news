"""Pipeline and container status detection.

Uses Docker Engine API via Unix socket when available (production),
falls back to local PID files (local dev without Docker).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from src.admin.schemas import ContainerStatus, PipelineServiceStatus, PipelineStatus

_DOCKER_SOCK = "/var/run/docker.sock"

_SERVICE_CONTAINERS = {
    "mcp": "knowledge-mcp",
    "neo4j": "knowledge-neo4j",
    "caddy": "knowledge-caddy",
    "admin": "knowledge-admin",
}


def _docker_available() -> bool:
    return os.path.exists(_DOCKER_SOCK)


def _create_docker_client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=_DOCKER_SOCK)
    return httpx.Client(transport=transport, base_url="http://localhost", timeout=5.0)


def get_mode() -> str:
    return "docker" if _docker_available() else "pidfile"


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------


def _docker_pipeline_status() -> PipelineStatus:
    try:
        with _create_docker_client() as client:
            resp = client.get("/containers/json", params={"all": "true"})
            resp.raise_for_status()
            containers = resp.json()
    except (httpx.HTTPError, OSError):
        return PipelineStatus(
            fetch=PipelineServiceStatus(running=False),
            offline=PipelineServiceStatus(running=False),
        )

    result = {
        "fetch": PipelineServiceStatus(running=False),
        "offline": PipelineServiceStatus(running=False),
    }

    for c in containers:
        if c.get("State") != "running":
            continue
        cmd = c.get("Command", "")
        started_at = _parse_docker_timestamp(c.get("Created"))

        if "_run_fetch" in cmd:
            result["fetch"] = PipelineServiceStatus(
                running=True, started_at=started_at, command=["_run_fetch"],
            )
        elif "_run_offline" in cmd:
            result["offline"] = PipelineServiceStatus(
                running=True, started_at=started_at, command=["_run_offline"],
            )

    return PipelineStatus(**result)


def _pidfile_pipeline_status() -> PipelineStatus:
    from src.process_manager import SERVICES, is_process_alive, read_pid, remove_pid

    result = {}
    for svc in SERVICES:
        info = read_pid(svc)
        if info and is_process_alive(info["pid"]):
            result[svc] = PipelineServiceStatus(
                running=True,
                pid=info["pid"],
                started_at=info.get("started_at"),
                command=info.get("command"),
            )
        else:
            if info:
                remove_pid(svc)
            result[svc] = PipelineServiceStatus(running=False)

    return PipelineStatus(**result)


def get_pipeline_status() -> PipelineStatus:
    if _docker_available():
        return _docker_pipeline_status()
    return _pidfile_pipeline_status()


# ---------------------------------------------------------------------------
# Container status
# ---------------------------------------------------------------------------


def _parse_docker_timestamp(created: Any) -> str | None:
    """Convert Docker's ``Created`` field (Unix timestamp int) to ISO string."""
    if created is None:
        return None
    try:
        return datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def get_container_statuses() -> list[ContainerStatus]:
    if not _docker_available():
        return []

    try:
        with _create_docker_client() as client:
            resp = client.get("/containers/json", params={"all": "true"})
            resp.raise_for_status()
            containers = resp.json()
    except (httpx.HTTPError, OSError):
        return []

    by_name: dict[str, dict] = {}
    for c in containers:
        for n in c.get("Names", []):
            by_name[n.lstrip("/")] = c

    result = []
    for name, container_name in _SERVICE_CONTAINERS.items():
        c = by_name.get(container_name)
        if c is None:
            result.append(ContainerStatus(
                name=name, container_name=container_name,
                running=False, status="not found",
            ))
        else:
            state = c.get("State", "unknown")
            result.append(ContainerStatus(
                name=name, container_name=container_name,
                running=(state == "running"),
                status=c.get("Status", state),
                started_at=_parse_docker_timestamp(c.get("Created")),
            ))

    return result
