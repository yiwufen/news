---
name: knowledge-search
description: Search the financial knowledge base for entities, events, relationships, timelines, and risk assessments. Use when the user asks about a company, person, or financial topic that requires structured knowledge retrieval.
---

# Knowledge Search

Search the financial knowledge base via `knowledge-cli search`.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--entities` | list[str] | `[]` | Entity names, e.g. `"小米集团" "苹果公司"` |
| `--intent` | str | `ENTITY_OVERVIEW` | Query intent (see below) |
| `--time-range` | str | None | `START:END` in ISO dates, e.g. `2025-04-01:2026-04-13` |
| `--event-types` | list[str] | None | Filter by event types, e.g. `"债务违约" "股权质押"` |
| `--hops` | int | `1` | Graph expansion hop count (1-5) |
| `--target-entity` | str | None | Second entity for A-B relationship queries |
| `--top-k` | int | `20` | Max results to return |
| `--graph-enabled` / `--no-graph` | flag | enabled | Toggle knowledge graph expansion |

## Intent Types

- `ENTITY_OVERVIEW` — General entity overview (default)
- `ENTITY_TIMELINE` — Entity timeline analysis
- `RELATIONSHIP_QUERY` — Relationship between two entities (requires `--target-entity`)
- `COMPARATIVE_ANALYSIS` — Compare multiple entities
- `EVENT_ANALYSIS` — Analyze specific events
- `TOPIC_RESEARCH` — Research a topic across entities

Risk / guarantee / event-impact content is retrieved by combining the intents
above with `--event-types` filters (e.g. risk = overview + debt_default /
regulatory types; guarantee = RELATIONSHIP_QUERY via graph expand).

## Usage

Construct the command based on the user's request:

```bash
knowledge-cli search --entities "小米集团"
```

```bash
knowledge-cli search --entities "小米集团" --time-range 2025-04-01:2026-04-13 --intent ENTITY_TIMELINE
```

```bash
knowledge-cli search --entities "小米集团" --intent RELATIONSHIP_QUERY --target-entity "苹果公司" --hops 3
```

```bash
knowledge-cli search --entities "小米集团" "腾讯" --intent COMPARATIVE_ANALYSIS
```

## Output

Returns JSON with:

- `knowledge_units` — Matched evidence units (summaries, entities, evidence text)
- `entities` — Matched entity records from text retrieval
- `event_clusters` — Aggregated event views from text retrieval
- `graph_data` — Graph metadata:
  - `summary` — Start entities, cluster count, entity count
  - `clusters_overview` — Lightweight cluster list (id, title, type, member_count, neighbor_entities, hit_reasons). Use this to decide which clusters to explore further.
  - `nodes`/`edges`/`paths` — Only present for relationship path queries (RELATIONSHIP_QUERY)
- `retrieval` — BM25 search metadata and scores
- `errors` — Any soft failures

## Tier-2 Graph Expansion

When you need full graph detail for specific clusters, use:

```bash
knowledge-cli graph-expand --cluster-ids "clu_abc123" "clu_def456"
```

Returns JSON with `nodes`, `edges`, `paths` for the selected clusters.

## Instructions

1. Parse the user's request to determine the appropriate `--intent`, `--entities`, and optional filters.
2. Run the command using `PYTHONIOENCODING=utf-8 knowledge-cli search ...` to ensure consistent encoding across systems.
3. The output is JSON printed to stdout with all non-ASCII characters escaped (`\uXXXX`). Parse it and present the key findings to the user.
4. If the user's query mentions two entities and their relationship, use `--intent RELATIONSHIP_QUERY --target-entity "B" --hops N`.
5. If the user asks about time progression, use `--intent ENTITY_TIMELINE` with a `--time-range`.
6. Entity names containing spaces do NOT need extra quoting beyond the surrounding quotes.
7. Prefer Chinese entity names. Common English short names (e.g. `BYD`, `CATL`, `NIO`) resolve
   automatically; obscure English names may not resolve, so convert them to Chinese first.
8. When the user asks about specific clusters or wants deeper analysis, note the `cluster_id` values from `graph_data.clusters_overview` and run `knowledge-cli graph-expand --cluster-ids <ids>` to get full nodes, edges, and paths.

## Examples from user arguments

If the user invokes `$knowledge-search 小米集团`, run:

```bash
knowledge-cli search --entities "小米集团"
```

If the user invokes `$knowledge-search 小米和腾讯的关系`, determine intent and entities, then run:

```bash
knowledge-cli search --entities "小米集团" --intent RELATIONSHIP_QUERY --target-entity "腾讯" --hops 2
```
