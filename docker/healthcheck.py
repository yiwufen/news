"""Container healthcheck for the knowledge-cli MCP image.

The same image runs in two roles:

* ``knowledge-mcp`` — the long-lived Streamable HTTP server, listening on
  port 8000.
* ``knowledge-ingestion`` (launched via ``docker compose run --rm``) — the
  offline ingestion loop, which does NOT listen on any port.

A single healthcheck serves both: the MCP container is healthy if its port is
open; the ingestion container is healthy if its processing loop is still
advancing (``data/logs/offline.log`` was written within the last 15 minutes).
"""

from __future__ import annotations

import os
import socket
import sys
import time

_MCP_PORT = 8000
_OFFLINE_LOG = "/app/data/logs/offline.log"
# Ingestion loop interval is 5 min; allow up to 3 missed cycles (15 min)
# before declaring the loop stalled.
_STALE_SECONDS = 900


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


def _log_fresh(path: str, max_age: float) -> bool:
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age


def main() -> int:
    if _port_open(_MCP_PORT):
        # Long-lived MCP server role.
        return 0
    if _log_fresh(_OFFLINE_LOG, _STALE_SECONDS):
        # Offline ingestion loop role — still advancing.
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
