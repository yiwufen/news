"""Container healthcheck for the knowledge-cli MCP image.

The same image runs in three roles:

* ``knowledge-mcp`` — the long-lived Streamable HTTP server, listening on
  port 8000.
* ``knowledge-ingestion`` (launched via ``docker compose run --rm``) — the
  offline ingestion loop, which does NOT listen on any port; it advances by
  writing ``data/logs/offline.log`` each cycle.
* ``knowledge-fetch`` (launched via ``docker compose run --rm``) — the crawl
  loop, also port-less; it advances by writing ``data/logs/fetch.log``.

A single healthcheck serves all three: the MCP container is healthy if its
port is open; a loop container is healthy if its log was written within the
staleness window (the loop is still advancing).
"""

from __future__ import annotations

import os
import socket
import sys
import time

_MCP_PORT = 8000
_LOOP_LOGS = (
    "/app/data/logs/offline.log",  # ingestion loop
    "/app/data/logs/fetch.log",     # crawl loop
)
# Loop intervals are 5–15 min; allow up to ~3 missed cycles before declaring a
# loop stalled.
_STALE_SECONDS = 1800


def _port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(3)
    try:
        sock.connect(("localhost", port))
    except OSError:
        return False
    else:
        return True
    finally:
        sock.close()


def _any_log_fresh(paths: tuple[str, ...], max_age: float) -> bool:
    now = time.time()
    return any(
        os.path.exists(path) and (now - os.path.getmtime(path)) < max_age
        for path in paths
    )


def main() -> int:
    if _port_open(_MCP_PORT):
        # Long-lived MCP server role.
        return 0
    if _any_log_fresh(_LOOP_LOGS, _STALE_SECONDS):
        # A background loop role (ingestion/fetch) — still advancing.
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
