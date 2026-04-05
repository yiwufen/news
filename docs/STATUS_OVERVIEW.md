# Current Status Overview

This document summarizes the actual supported mainline in the repo today.
If any document disagrees, follow [docs/SHARED_RULES.md](docs/SHARED_RULES.md) first and [PROGRESS.md](../PROGRESS.md) second.

## Mainline

The project mainline is now the knowledge foundation:

`RawDocument -> KnowledgeUnit -> Entity / EventCluster -> graph -> retrieval`

Official entrypoints:

- `run_continuous(graph_enabled=True)`: offline knowledge ingestion and indexing
- `run_pipeline(raw_query=..., graph_enabled=True)`: unified knowledge retrieval

Legacy risk-oriented outputs are no longer part of the supported public interface.

## Public Outputs

`run_continuous()` returns:

- `knowledge_units_extracted`
- `knowledge_units_saved`
- `entities_saved`
- `clusters_saved`
- `nodes_created`
- `edges_created`
- `errors`

`run_pipeline()` returns:

- `request_id`
- `query`
- `source`
- `retrieval`
- `graph`
- `knowledge_units`
- `entities`
- `event_clusters`
- `timeline_data`
- `total_count`
- `verification`
- `errors`

It does not return legacy wrapper fields such as `particles_count`, `report`, `risk_assessment`, `comparison_report`, or `event_impact`.

## Current Capabilities

The following are already on the mainline:

- SQLite-backed `RawDocument`, `KnowledgeUnit`, `Entity`, and `EventCluster` storage
- fail-fast `KnowledgeUnit` extraction
- conservative entity resolution and event clustering
- Neo4j sync for `Entity` and `EventCluster`
- FTS5 plus embedding-backed retrieval storage
- BM25 + vector hybrid retrieval with fusion ranking
- timeline projection from retrieved knowledge units
- self-healing repair for older materialized rows and legacy cluster payloads

## Remaining Product Work

Migration cleanup is complete. The next work is product-facing, not legacy-facing:

- graph-aware retrieval as a first-class retrieval mode
- a stable skill-facing retrieval contract
- higher-level skills built on the knowledge foundation

## Verification

See [PROGRESS.md](../PROGRESS.md) for the latest validation snapshot, including:

- `uv run pytest`
- `uv run pyright .`
