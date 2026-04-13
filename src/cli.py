"""knowledge-cli: CLI interface to the financial knowledge retrieval service.

Usage::

    knowledge-cli search --entities "小米集团" --time-range 2025-04-01:2026-04-13
    knowledge-cli ingest --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from src.orchestration.graph import run_pipeline
from src.orchestration.result import PipelineResult
from src.pipeline.continuous import run_continuous
from src.schemas.query import IntentType, make_query


def cmd_search(args: argparse.Namespace) -> None:
    """Search knowledge base and output PipelineResult as JSON to stdout."""
    time_range = None
    if args.time_range:
        parts = args.time_range.split(":")
        if len(parts) != 2:
            print("Error: --time-range must be START:END (ISO dates)", file=sys.stderr)
            sys.exit(1)
        time_range = (parts[0], parts[1])

    intent = IntentType.ENTITY_OVERVIEW
    if args.intent:
        try:
            intent = IntentType(args.intent)
        except ValueError:
            valid = ", ".join(t.value for t in IntentType)
            print(f"Error: invalid intent '{args.intent}'. Valid: {valid}", file=sys.stderr)
            sys.exit(1)

    structured_query = make_query(
        entities=args.entities or [],
        intent=intent,
        time_range=time_range,
        event_types=args.event_types,
        hops=args.hops or 1,
        target_entity=args.target_entity,
    )

    result: PipelineResult = run_pipeline(
        structured_query=structured_query,
        graph_enabled=args.graph_enabled,
        top_k=args.top_k,
        hops=args.hops,
    )

    json.dump(result.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def cmd_ingest(args: argparse.Namespace) -> None:
    """Run the continuous ingestion pipeline."""
    result = run_continuous(
        batch_size=args.batch_size,
        graph_enabled=args.graph_enabled,
        incremental=args.incremental,
        dry_run=args.dry_run,
    )
    json.dump(
        {
            "knowledge_units_extracted": result.knowledge_units_extracted,
            "knowledge_units_saved": result.knowledge_units_saved,
            "entities_saved": result.entities_saved,
            "clusters_saved": result.clusters_saved,
            "nodes_created": result.nodes_created,
            "edges_created": result.edges_created,
            "errors": result.errors,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="knowledge-cli",
        description="Financial knowledge retrieval CLI for agent consumption",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    search_parser = subparsers.add_parser("search", help="Search knowledge base")
    search_parser.add_argument(
        "--entities", nargs="+", default=[], help="Entity names to search"
    )
    search_parser.add_argument(
        "--time-range",
        default=None,
        help="Time range as START:END (ISO date format, e.g. 2025-04-01:2026-04-13)",
    )
    search_parser.add_argument(
        "--event-types", nargs="+", default=None, help="Filter by event types"
    )
    search_parser.add_argument(
        "--intent",
        default=None,
        help="Intent type (default: ENTITY_OVERVIEW)",
    )
    search_parser.add_argument(
        "--hops", type=int, default=None,
        help="Entity-to-Entity hop count for graph expansion (1-5, default: 1)"
    )
    search_parser.add_argument(
        "--target-entity", default=None,
        help="Second entity for A-B relationship path query (requires --intent RELATIONSHIP_QUERY)"
    )
    search_parser.add_argument(
        "--top-k", type=int, default=20, help="Max results to return (default: 20)"
    )
    search_parser.add_argument(
        "--graph-enabled", dest="graph_enabled", action="store_true", default=True
    )
    search_parser.add_argument(
        "--no-graph", dest="graph_enabled", action="store_false"
    )
    search_parser.set_defaults(func=cmd_search)

    # --- ingest ---
    ingest_parser = subparsers.add_parser("ingest", help="Run offline ingestion")
    ingest_parser.add_argument(
        "--batch-size", type=int, default=10, help="Documents per batch (default: 10)"
    )
    ingest_parser.add_argument(
        "--graph-enabled", dest="graph_enabled", action="store_true", default=True
    )
    ingest_parser.add_argument(
        "--no-graph", dest="graph_enabled", action="store_false"
    )
    ingest_parser.add_argument(
        "--incremental", dest="incremental", action="store_true", default=True
    )
    ingest_parser.add_argument(
        "--full", dest="incremental", action="store_false"
    )
    ingest_parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
