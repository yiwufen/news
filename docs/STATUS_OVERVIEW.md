# Current Status Overview

This document summarizes the actual supported mainline in the repo today.
If any document disagrees, follow [docs/SHARED_RULES.md](SHARED_RULES.md).

## Mainline

The project mainline is now the knowledge foundation:

`RawDocument -> KnowledgeUnit -> Entity / EventCluster -> graph -> retrieval`

Official entrypoints:

- `run_continuous(graph_enabled=True)`: offline knowledge ingestion and indexing
- `run_pipeline(raw_query=..., graph_enabled=True)`: unified knowledge retrieval
- `run_skill_query(raw_query=..., graph_enabled=True)`: stable skill-facing contract over retrieval results

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
- `total_count`
- `errors`

It does not return legacy wrapper fields such as `particles_count`, `report`, `risk_assessment`, `comparison_report`, or `event_impact`.

`run_skill_query()` returns:

- `contract_version`
- `ok`
- `skill_type`
- `source`
- `query`
- `summary`
- `capabilities`
- `payload`
- `verification`
- `errors`

## Current Capabilities

The following are already on the mainline:

- SQLite-backed `RawDocument`, `KnowledgeUnit`, `Entity`, and `EventCluster` storage
- fail-fast `KnowledgeUnit` extraction
- conservative entity resolution and event clustering
- Neo4j sync for `Entity` and `EventCluster`
- FTS5 retrieval storage
- BM25 + structured filtering + tiered scoring
- graph-enhanced retrieval over `Entity -> EventCluster` with formal `nodes` / `edges` / `paths` output
- timeline projection from retrieved knowledge units
- stable skill-facing contract V1 for `ENTITY_OVERVIEW`, `ENTITY_TIMELINE`, `EVENT_ANALYSIS`, `RELATIONSHIP_QUERY`, `RISK_ASSESSMENT`, and `GUARANTEE_ANALYSIS`
- self-healing repair for older materialized rows and legacy cluster payloads

`articles=...` direct input remains an ad-hoc/debug path. It performs temporary
online extraction and in-memory retrieval, does not use graph enhancement, and
is not the formal knowledge-base ingestion path.

`graph_enabled=False` is reserved for tests, debugging, and local operational
triage. The supported mainline treats graph sync/retrieval as enabled by
default and fail-open on read-path graph errors.

## Remaining Product Work

Migration cleanup is complete. The next work is product-facing, not legacy-facing:

- higher-level skills built on the knowledge foundation
- API packaging over the current retrieval and skill-facing contract

## Verification

Run locally:

- `uv run pytest`
- `uv run pyright .`
