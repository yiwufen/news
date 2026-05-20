"""knowledge-cli: CLI interface to the financial knowledge retrieval service.

Usage::

    knowledge-cli search --entities "小米集团" --time-range 2025-04-01:2026-04-13
    knowledge-cli ingest --dry-run
    knowledge-cli start --graph-enabled
    knowledge-cli stop
    knowledge-cli status
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.orchestration.graph import run_pipeline
from src.paths import DEFAULT_DB_PATH
from src.orchestration.result import PipelineResult
from src.pipeline.continuous import run_continuous
from src.process_manager import (
    SERVICES,
    is_process_alive,
    read_pid,
    remove_pid,
    spawn_process,
    stop_process,
    write_pid,
)
from src.schemas.query import IntentType, make_query


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

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

    # Capture stdout during pipeline execution to isolate Neo4j driver warnings
    # that would otherwise pollute the JSON output.
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        result: PipelineResult = run_pipeline(
            structured_query=structured_query,
            graph_enabled=args.graph_enabled,
            top_k=args.top_k,
            hops=args.hops,
            db_path=args.db,
        )
    finally:
        sys.stdout = real_stdout

    # Forward any non-JSON warnings to stderr for diagnostics.
    captured_text = captured.getvalue()
    if captured_text.strip():
        for line in captured_text.splitlines():
            if line.strip():
                print(line, file=sys.stderr)

    json.dump(result.to_dict(), sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")


def cmd_graph_expand(args: argparse.Namespace) -> None:
    """Expand specific graph clusters into full detail (Tier-2)."""
    from src.orchestration.graph import expand_graph_detail

    result = expand_graph_detail(
        cluster_ids=args.cluster_ids,
        db_path=args.db,
    )
    json.dump(result, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# ingest (single-shot)
# ---------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> None:
    """Run the continuous ingestion pipeline."""
    result = run_continuous(
        batch_size=args.batch_size,
        graph_enabled=args.graph_enabled,
        incremental=args.incremental,
        dry_run=args.dry_run,
        db_path=args.db,
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


# ---------------------------------------------------------------------------
# index-vectors
# ---------------------------------------------------------------------------

def cmd_index_vectors(args: argparse.Namespace) -> None:
    """Build or rebuild the vector index for dense retrieval."""
    from src.retrieval.indexing import build_vector_index, rebuild_vector_index
    from src.retrieval.vector_index import VectorIndex
    from src.retrieval.embedding import OpenAICompatEmbedding

    if args.rebuild:
        count = rebuild_vector_index(db_path=args.db)
        action = "Rebuilt"
    else:
        count = build_vector_index(db_path=args.db)
        action = "Indexed"

    # Report status
    provider = OpenAICompatEmbedding()
    idx = VectorIndex(args.db, provider)
    total = idx.indexed_count()

    json.dump(
        {
            "action": action.lower(),
            "new_embeddings": count,
            "total_vectors": total,
            "model": provider.model_name,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# start / stop / status — process management
# ---------------------------------------------------------------------------

def _spawn_service(service: str, extra_args: list[str]) -> None:
    """Spawn a child process running ``_run_<service>`` and record its PID."""
    info = read_pid(service)
    if info and is_process_alive(info["pid"]):
        print(f"{service}: already running (PID {info['pid']})", file=sys.stderr)
        return

    # Clean up stale PID file
    if info:
        remove_pid(service)

    command = [sys.executable, "-m", "src.cli", f"_run_{service}", *extra_args]
    pid = spawn_process(command)
    write_pid(service, pid, command)
    print(f"{service}: started (PID {pid})")


def cmd_start(args: argparse.Namespace) -> None:
    """Start fetch and/or offline services."""
    start_fetch = not args.offline_only
    start_offline = not args.fetch_only

    if start_fetch:
        fetch_args = [
            "--limit", str(args.fetch_limit),
            "--interval", str(args.fetch_interval),
            "--db", args.db,
        ]
        _spawn_service("fetch", fetch_args)

    if start_offline:
        offline_args = [
            "--batch-size", str(args.process_batch_size),
            "--interval", str(args.process_interval),
            "--db", args.db,
        ]
        if args.graph_enabled:
            offline_args.append("--graph-enabled")
        if args.time_window:
            offline_args.extend(["--time-window", args.time_window])
        _spawn_service("offline", offline_args)


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop running services."""
    targets = []
    if args.fetch:
        targets.append("fetch")
    if args.offline:
        targets.append("offline")
    if not targets:
        targets = list(SERVICES)

    for svc in targets:
        info = read_pid(svc)
        if not info:
            print(f"{svc}: not running")
            continue
        if not is_process_alive(info["pid"]):
            remove_pid(svc)
            print(f"{svc}: not running (cleaned stale PID file)")
            continue
        stop_process(info["pid"])
        remove_pid(svc)
        print(f"{svc}: stopped (PID {info['pid']})")


def cmd_status(args: argparse.Namespace) -> None:
    """Show running process status."""
    for svc in SERVICES:
        info = read_pid(svc)
        if not info:
            print(f"{svc}: not running")
            continue
        if not is_process_alive(info["pid"]):
            remove_pid(svc)
            print(f"{svc}: not running (cleaned stale PID file)")
            continue
        started = info.get("started_at", "unknown")
        print(f"{svc}: running (PID {info['pid']}, since {started})")


# ---------------------------------------------------------------------------
# Hidden subcommands — child process entry points
# ---------------------------------------------------------------------------

def _setup_child_logging(log_path: str) -> None:
    """Configure logging for a child process to write to a log file."""
    from src.utils.logging import setup_logging

    setup_logging(level=logging.INFO, log_file=log_path, use_color=False)


def cmd_run_fetch(args: argparse.Namespace) -> None:
    """Internal: continuous fetch loop (launched as subprocess by ``start``)."""
    _setup_child_logging("data/logs/fetch.log")
    from collectors.eastmoney_crawler import EastMoneyCrawler

    crawler = EastMoneyCrawler(db_path=args.db)
    crawler.run(page_size=args.limit, continuous=True, interval=args.interval)


def cmd_run_offline(args: argparse.Namespace) -> None:
    """Internal: continuous offline loop (launched as subprocess by ``start``)."""
    _setup_child_logging("data/logs/offline.log")
    from src.pipeline.continuous import ContinuousPipeline
    from src.knowledge_base import KnowledgeUnitRepository
    from src.retrieval.indexing import KnowledgeIndexBuilder, try_create_vector_index

    ku_repo = KnowledgeUnitRepository(args.db)
    vector_index = try_create_vector_index(args.db)
    index_builder = KnowledgeIndexBuilder(ku_repo, vector_index=vector_index)

    pipeline = ContinuousPipeline(
        batch_size=args.batch_size,
        graph_enabled=args.graph_enabled,
        incremental=True,
        db_path=args.db,
        index_builder=index_builder,
    )

    print("Starting offline processing loop ...", flush=True)
    while True:
        result = pipeline.run(time_window=args.time_window or None, dry_run=False)
        payload = asdict(result) if is_dataclass(result) else result
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        time.sleep(args.interval)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

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
    search_parser.add_argument(
        "--db", type=str, default=DEFAULT_DB_PATH, help="SQLite database path"
    )
    search_parser.set_defaults(func=cmd_search)

    # --- graph-expand ---
    expand_parser = subparsers.add_parser(
        "graph-expand", help="Expand graph cluster details (Tier-2)"
    )
    expand_parser.add_argument(
        "--cluster-ids", nargs="+", required=True,
        help="Cluster IDs to expand",
    )
    expand_parser.add_argument(
        "--db", type=str, default=DEFAULT_DB_PATH, help="SQLite database path"
    )
    expand_parser.set_defaults(func=cmd_graph_expand)

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
    ingest_parser.add_argument(
        "--db", type=str, default=DEFAULT_DB_PATH, help="SQLite database path"
    )
    ingest_parser.set_defaults(func=cmd_ingest)

    # --- index-vectors ---
    idx_vec_parser = subparsers.add_parser(
        "index-vectors", help="Build vector index for dense retrieval"
    )
    idx_vec_parser.add_argument(
        "--rebuild", action="store_true",
        help="Full rebuild (clear existing and re-embed all)"
    )
    idx_vec_parser.add_argument(
        "--db", type=str, default=DEFAULT_DB_PATH,
        help="SQLite database path"
    )
    idx_vec_parser.set_defaults(func=cmd_index_vectors)

    # --- start ---
    start_parser = subparsers.add_parser("start", help="Start fetch + offline services")
    start_parser.add_argument("--fetch-limit", type=int, default=100,
                              help="Items per fetch (default: 100)")
    start_parser.add_argument("--fetch-interval", type=int, default=900,
                              help="Fetch interval in seconds (default: 900)")
    start_parser.add_argument("--process-batch-size", type=int, default=10,
                              help="Offline batch size (default: 10)")
    start_parser.add_argument("--process-interval", type=int, default=300,
                              help="Offline loop interval in seconds (default: 300)")
    start_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH,
                              help="SQLite database path")
    start_parser.add_argument("--graph-enabled", action="store_true",
                              help="Enable knowledge graph sync for offline process")
    start_parser.add_argument("--time-window", type=str, default="",
                              help="Optional ISO week window for offline process")
    start_parser.add_argument("--fetch-only", action="store_true",
                              help="Start fetch only (skip offline)")
    start_parser.add_argument("--offline-only", action="store_true",
                              help="Start offline only (skip fetch)")
    start_parser.set_defaults(func=cmd_start)

    # --- stop ---
    stop_parser = subparsers.add_parser("stop", help="Stop running services")
    stop_parser.add_argument("--fetch", action="store_true", help="Stop fetch only")
    stop_parser.add_argument("--offline", action="store_true", help="Stop offline only")
    stop_parser.set_defaults(func=cmd_stop)

    # --- status ---
    status_parser = subparsers.add_parser("status", help="Show running process status")
    status_parser.set_defaults(func=cmd_status)

    # --- hidden: _run_fetch ---
    run_fetch_parser = subparsers.add_parser("_run_fetch")
    run_fetch_parser.add_argument("--limit", type=int, default=100)
    run_fetch_parser.add_argument("--interval", type=int, default=900)
    run_fetch_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH)
    run_fetch_parser.set_defaults(func=cmd_run_fetch)

    # --- hidden: _run_offline ---
    run_offline_parser = subparsers.add_parser("_run_offline")
    run_offline_parser.add_argument("--batch-size", type=int, default=10)
    run_offline_parser.add_argument("--interval", type=int, default=300)
    run_offline_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH)
    run_offline_parser.add_argument("--time-window", type=str, default="")
    run_offline_parser.add_argument("--graph-enabled", dest="graph_enabled",
                                     action="store_true", default=False)
    run_offline_parser.set_defaults(func=cmd_run_offline)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
