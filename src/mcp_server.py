"""MCP server exposing knowledge-cli as remote tools via Streamable HTTP."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from src.paths import DEFAULT_DB_PATH
from src.schemas.query import IntentType, make_query


def create_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    db_path: str = DEFAULT_DB_PATH,
) -> FastMCP:
    """Create a configured FastMCP server with all tools registered."""

    mcp = FastMCP(
        name="knowledge-cli",
        instructions=(
            "Financial knowledge retrieval service. "
            "Search for entities, events, and relationships in the financial knowledge base. "
            "Use search_knowledge for general queries, and expand_graph_detail to drill into "
            "specific graph clusters."
        ),
        host=host,
        port=port,
        stateless_http=True,
    )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def search_knowledge(
        entities: list[str],
        intent: str = "ENTITY_OVERVIEW",
        time_range: str | None = None,
        event_types: list[str] | None = None,
        target_entity: str | None = None,
        hops: int = 1,
        top_k: int = 20,
    ) -> dict[str, Any]:
        """Search the financial knowledge base for entities, events, and relationships.

        Args:
            entities: Entity names to search for, e.g. ["小米集团", "比亚迪"].
            intent: Intent type. One of ENTITY_OVERVIEW, ENTITY_TIMELINE, RELATIONSHIP_QUERY,
                EVENT_ANALYSIS, COMPARATIVE_ANALYSIS, RISK_ASSESSMENT, TOPIC_RESEARCH,
                EVENT_IMPACT_ANALYSIS, GUARANTEE_ANALYSIS.
            time_range: Time range as "START:END" in ISO date format,
                e.g. "2025-04-01:2026-05-24".
            event_types: Filter by event types, e.g. ["earnings_release", "executive_change"].
            target_entity: Second entity for A-B relationship path queries.
                Requires intent=RELATIONSHIP_QUERY.
            hops: Entity-to-Entity hop count for graph expansion (1-5, default: 1).
            top_k: Max results to return (default: 20).
        """
        from src.orchestration.graph import run_pipeline

        try:
            parsed_intent = IntentType(intent)
        except ValueError:
            valid = ", ".join(t.value for t in IntentType)
            return {"error": f"Invalid intent '{intent}'. Valid values: {valid}"}

        parsed_time_range = None
        if time_range:
            parts = time_range.split(":")
            if len(parts) != 2:
                return {"error": "time_range must be START:END (ISO dates)"}
            parsed_time_range = (parts[0], parts[1])

        structured_query = make_query(
            entities=entities,
            intent=parsed_intent,
            time_range=parsed_time_range,
            event_types=event_types,
            hops=hops,
            target_entity=target_entity,
        )

        result = run_pipeline(
            structured_query=structured_query,
            top_k=top_k,
            hops=hops,
            db_path=db_path,
        )

        return result.to_dict()

    @mcp.tool()
    def expand_graph_detail(
        cluster_ids: list[str],
    ) -> dict[str, Any]:
        """Expand specific graph clusters into full detail (Tier-2).

        Use this after search_knowledge to drill into clusters returned in the graph_data
        section of search results.

        Args:
            cluster_ids: List of cluster IDs to expand.
        """
        from src.orchestration.graph import expand_graph_detail as _expand

        return _expand(cluster_ids=cluster_ids, db_path=db_path)

    return mcp
