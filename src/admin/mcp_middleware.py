"""ASGI middleware that intercepts MCP tool calls for usage tracking."""

from __future__ import annotations

import json
import time

from src.admin.mcp_logger import MCPCallLogger


class MCPCallTrackingMiddleware:
    """Raw ASGI middleware that parses JSON-RPC bodies to detect tools/call.

    Reads the request body once, inspects it for MCP tool invocations,
    replays the body for downstream consumers, and logs after the response.
    """

    def __init__(self, app, logger: MCPCallLogger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        # Read full request body
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                body_chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)

        full_body = b"".join(body_chunks)

        # Parse JSON-RPC to detect tool calls
        call_meta = _extract_call_meta(full_body)

        # Replay body for downstream
        body_replayed = False

        async def replay_receive():
            nonlocal body_replayed
            if not body_replayed:
                body_replayed = True
                return {
                    "type": "http.request",
                    "body": full_body,
                    "more_body": False,
                }
            return await receive()

        if call_meta is None:
            await self.app(scope, replay_receive, send)
            return

        # Track this tool call
        start_ts = time.perf_counter()
        response_status: int = 200

        async def tracking_send(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, replay_receive, tracking_send)
        except Exception:
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            self.logger.log(
                tool_name=call_meta["tool_name"],
                intent=call_meta.get("intent"),
                entity_count=call_meta.get("entity_count", 0),
                success=False,
                duration_ms=duration_ms,
                error_message="Internal server error",
                client_info=None,
            )
            raise
        else:
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            is_success = 200 <= response_status < 300
            self.logger.log(
                tool_name=call_meta["tool_name"],
                intent=call_meta.get("intent"),
                entity_count=call_meta.get("entity_count", 0),
                success=is_success,
                duration_ms=duration_ms,
                error_message=None if is_success else f"HTTP {response_status}",
                client_info=None,
            )


def _extract_call_meta(body: bytes) -> dict | None:
    """Parse JSON-RPC body and extract tool call metadata. Returns None if not a tool call."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    # JSON-RPC may be a single request or a batch (list)
    if isinstance(data, list):
        # Look at the first tools/call in a batch
        for item in data:
            result = _parse_single(item)
            if result:
                return result
        return None

    return _parse_single(data)


def _parse_single(data: dict) -> dict | None:
    if data.get("method") != "tools/call":
        return None

    params = data.get("params", {})
    tool_name = params.get("name", "unknown")
    arguments = params.get("arguments", {})

    meta: dict = {"tool_name": tool_name}

    if tool_name == "search_knowledge":
        meta["intent"] = arguments.get("intent")
        entities = arguments.get("entities", [])
        meta["entity_count"] = len(entities) if isinstance(entities, list) else 0
    elif tool_name == "expand_graph_detail":
        cluster_ids = arguments.get("cluster_ids", [])
        meta["entity_count"] = len(cluster_ids) if isinstance(cluster_ids, list) else 0

    return meta
