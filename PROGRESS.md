# 项目开发进度

## 当前定位

项目已从“金融风险研判 Agent”重定位为“金融知识检索底座”。

当前阶段目标：

- 把原始消息加工为可检索状态
- 建立 `KnowledgeUnit` / `EventCluster` / `Entity` 三层知识结构
- 构建文本、语义、图谱三类正式索引
- 为后续 skill 驱动的分析 agent 提供统一知识底座

风险分析、时间线、主题研究、关系扩展等能力均视为后续消费该底座的 skill。

---

## 当前状态概览

| 层级 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| 1. 原始文档接入 | ✅ 已完成 | 100% | SQLite 文档存储、测试数据与增量读取已具备 |
| 2. 文档知识化抽取 | ✅ 主线可用 | 85% | `run_continuous()` 已切到 `RawDocument -> KnowledgeUnit` 新主线，时间标准化、冲突检测已集成 |
| 3. 实体与事件归一 | ✅ 主线可用 | 85% | 已新增 `Entity` / `EventCluster` 保守归一与归并，多类型冲突检测与聚合视图已落地 |
| 4. 检索层 | ✅ 主线可用 | 85% | `run_pipeline()` 已切到混合检索主线，`KnowledgeUnit` FTS + 向量索引、融合排序、统一检索元数据与 `Entity` / `EventCluster` 检索入口已落地 |
| 5. 图谱层 | ✅ 主线可用 | 90% | 新离线路径已同步 `Entity + EventCluster + INVOLVED_IN`，`run_pipeline()` 已接入正式图谱增强检索、关系结果集与稳定输出契约 |
| 6. 消费层 | ✅ 已移除旧链路 | 100% | 不再兼容旧风险导向消费链路，入口直接面向知识检索 |

---

## 已有基础能力

### 数据接入与存储
- [x] SQLite 数据库管理 (`collectors/database.py`)
- [x] 新闻文章存储
- [x] 处理状态追踪
- [x] 增量批处理入口

### 双模式骨架
- [x] `run_continuous()` 离线流水线入口
- [x] `run_pipeline()` 任务入口
- [x] `run_skill_query()` skill-facing 契约入口
- [x] 阶段状态与错误追踪

### 抽取与图谱基础设施
- [x] `KnowledgeExtractor` LLM 结构化抽取能力
- [x] `KnowledgeGraphSync` 图谱同步能力
- [x] Neo4j 连接管理
- [x] 基础 Cypher 查询模板

### 基础检索
- [x] 文章检索器骨架
- [x] 结构化过滤基础能力
- [x] `KnowledgeUnit` / `Entity` / `EventCluster` 统一检索入口骨架

### 测试与工程
- [x] 单元测试与集成测试骨架
- [x] `uv` 环境与依赖管理
- [x] `pyright` 类型检查接入
- [x] `uv` 本地缓存目录固定为仓库内 `.uv-cache/`，避免用户目录缓存异常影响 `uv run`
- [x] `pytest` 缓存与临时目录固定到仓库内 `.tmp/`，避免在项目根生成随机 `pytest-cache-files-*` 临时目录
- [x] 建立项目级临时文件治理规则，并提供仓库内统一清理脚本，避免 pytest/Codex 调试产物污染项目根目录

---

## 已弃用的历史设计

以下内容仅作为 legacy 边界保留，不属于当前主线设计，也不得继续扩展进知识底座：

- `IntelligenceParticle` 作为核心数据契约
- `risk_signal` 作为抽取层中心字段
- `RiskReport` 作为默认终点产物
- “风险研判系统”作为项目定位
- 以风险传导为中心的图查询语义

如仍有业务需要，上述能力只能作为上层 skill 的消费逻辑存在，而不是知识底座主线的一部分。

---

## P0 重点任务

### 数据契约重构
- [x] 在共享规范中定义 `RawDocument` 规范
- [x] 在共享规范中定义 statement-level `KnowledgeUnit v1`
- [x] 在共享规范中定义 `EventCluster v1`
- [x] 在共享规范中定义 `Entity v1`
- [x] 在共享规范中明确 `KnowledgeUnit -> EventCluster` 保守归并规则
- [x] 在共享规范和入口文档中明确 legacy 隔离规则，避免新实现继续被旧风险代码带偏
- [x] 在代码中落地 `RawDocument` / `KnowledgeUnit` / `EventCluster` / `Entity` 模型
- [x] 设计并执行首批 SQLite 存储层迁移方案（`knowledge_units` / `entities` / `event_clusters` / `knowledge_processing_log`）

### 离线知识化流水线
- [x] 将 `run_continuous()` 主线输出从 `IntelligenceParticle` 迁移到 `KnowledgeUnit`
- [x] 将新离线路径的 Integrator 职责迁移为实体标准化、事件归并、图谱更新
- [x] 建立冲突保留与多来源聚合逻辑
- [x] 建立可追踪的离线知识化状态记录
- [x] 修复知识化主线稳定性问题：`ku_id` 可重放、图同步失败可重试
- [x] 收紧抽取策略：`KnowledgeUnit` 抽取默认 fail-fast，禁止因未配置或异常静默回退到启发式
- [x] 移除 legacy 回填：离线主线不再写入 `intelligence_particles`

### 图谱与 GraphRAG
- [x] 按 `Entity + EventCluster` 重构新离线路径图谱主模型
- [x] 定义节点、边与溯源约束
- [x] 让图谱成为正式可检索产物
- [x] 保证图结果可回溯到底层 `KnowledgeUnit`

### 消费链路清理
- [x] 删除 `heuristic` 抽取回退，抽取失败直接报错
- [x] 统一实体模块最终命名，移除 `entities_v2`
- [x] 让 `run_pipeline()` 直接面向知识检索，不再兼容旧消费链路
- [x] 图谱默认开启

### 检索系统
- [x] 建立 `KnowledgeUnit` 稀疏索引
- [x] 建立 `KnowledgeUnit` 向量索引
- [x] 建立 `Entity` 与 `EventCluster` 检索入口
- [x] 定义统一检索返回契约
- [x] 实现 BM25 / 向量检索 / 融合排序

---

## P1 后续任务

- [x] 设计面向 skill 的统一检索接口
- [ ] 将风险分析改造为消费知识底座的 skill
- [ ] 将时间线生成功能改造为消费知识底座的 skill
- [ ] 支持主题研究、事件影响分析 skill
- [x] 支持关系扩展 skill（`RELATIONSHIP_QUERY`）
- [ ] 设计多轮任务消费层
- [ ] 提供 API 封装

---

## 当前建议的迁移顺序

1. 重写共享规范与进度文档
2. 定义 `KnowledgeUnit v1` / `EventCluster v1` / `Entity v1`
3. 重构离线流水线输出与图谱更新逻辑
4. 建立正式多索引
5. 最后再重构任务消费层

---

## 运行说明

### 当前可用入口

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv('.env')
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=True)
print(result)
"
```

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv('.env')
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=True,
)
print(result)
"
```

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv('.env')
from src.skills import run_skill_query

result = run_skill_query(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=True,
)
print(result)
"
```

说明：

- 上述入口当前仍可运行
- `run_pipeline()` 已直接返回知识检索结果，不再兼容旧风险消费链路
- `run_skill_query()` 已提供稳定的 skill-facing V1 契约，统一返回 `summary` / `capabilities` / `payload`
- 图谱默认开启；显式传 `graph_enabled=False` 仅用于调试或测试
- 在当前 PowerShell heredoc / stdin 场景下，中文查询字符串可能被宿主链路降级成 `?`；做真实命令验证时，优先显式 `load_dotenv('.env')`，并避免依赖终端内联中文传参做最终判断
- 若要验证中文查询命中，优先在脚本文件中执行，或使用 Unicode 转义字符串，避免把 shell 编码问题误判为意图解析/检索问题

---

## 相关文档

- [docs/STATUS_OVERVIEW.md](docs/STATUS_OVERVIEW.md) - 当前实现进度与可见结果总览
- [docs/SHARED_RULES.md](docs/SHARED_RULES.md) - 项目共享规范真源
- [README.md](README.md) - 项目入口说明
- [AGENTS.md](AGENTS.md) - Codex 入口
- [CLAUDE.md](CLAUDE.md) - Claude Code 入口

项目级规则统一以 `docs/SHARED_RULES.md` 为准。

---

## 2026-04-04 Fix Update

- Graph sync is now usable again: `KnowledgeGraphSync` no longer writes Neo4j map properties for entity identifiers, and writes `primary_identifier` plus `identifiers_json` instead.
- Intent parsing is more stable: `IntentClassifier` now adds deterministic post-processing for time expressions and entity supplementation from the local entity repository when the LLM response is incomplete.
- Retrieval matching is more stable: `KnowledgeSearcher` now matches entity filters through normalized canonical names plus aliases instead of raw string contains only.
- Retrieval storage now self-heals stale SQLite materializations: `KnowledgeUnitRepository` backfills missing `entity_ids` from persisted payloads and rebuilds missing FTS rows on open, so older databases do not silently lose entity-filtered BM25 recall.
- Retrieval is now formally indexed: `KnowledgeUnitRepository` maintains SQLite FTS5 rows, stores persisted embeddings, and supports BM25 query plus filtered embedding hydration.
- Hybrid retrieval is now live: `KnowledgeSearcher` executes BM25 + vector recall with reciprocal rank fusion, returns retrieval metadata, and keeps `run_pipeline()` compatibility output stable.
- `run_pipeline()` now degrades to BM25-only retrieval when embedding credentials are absent, instead of failing the default knowledge-base query path.
- README and `docs/STATUS_OVERVIEW.md` are now aligned with the current code path: they no longer describe BM25 / vector / fusion retrieval as unfinished, and the inline run examples now use explicit `.env` loading to match actual execution behavior.
- Offline indexing is now part of the mainline: `ContinuousPipeline` builds embeddings after each batch, and `rebuild_knowledge_indexes()` can backfill FTS plus embeddings for existing knowledge bases.
- Offline processing logs now keep successfully persisted documents in `success` state when only embedding index post-processing fails, avoiding repeated incremental re-extraction.
- Windows pytest temp handling is stabilized for this repo test suite by replacing direct `tmp_path` usage with a repo-local temp fixture and disabling the cacheprovider plugin for test runs.
- Event clustering now produces an aggregated `EventCluster` view with `representative_ku_id`, `member_count`, `source_count`, `summary_variants`, `event_time_variants`, and `conflict_reasons`.
- Cluster conflict retention is now live: multi-source member evidence is preserved at cluster level, explicit member conflicts are carried forward, and adjacent-day explicit event-date disagreements are surfaced as `possible` conflicts instead of being silently flattened.
- Legacy cluster payloads now self-heal on read: when older SQLite rows are missing aggregation fields, `EventClusterRepository` rebuilds the cluster snapshot from persisted `KnowledgeUnit` members and writes the repaired payload back.
- `run_pipeline()` now returns enriched `event_clusters`, and Neo4j sync now stores cluster aggregation metadata alongside the existing node and edge provenance fields.
- Event cluster time handling is now range-aware: adjacent-day merged clusters match against their full `time_range`, so chained day-by-day reports stay in one cluster and date-filtered retrieval does not miss later member dates.
- Regression checks passed after the fix:
  - `uv run pytest`
  - `uv run pyright .`

---

## 2026-04-05 Real Run Verification

- Real regression checks passed again on **2026-04-05**:
  - `uv run pytest` -> `54 passed`
  - `uv run pyright .` -> `0 errors`
- Current local knowledge base snapshot used in verification:
  - `news_articles: 80`
  - `knowledge_units: 528`
  - `entities: 489`
  - `event_clusters: 519`
  - `knowledge_processing_log: 80`
- Real incremental `run_continuous(graph_enabled=False)` completed without processing errors and returned zero new units/clusters, which matches the current fully processed local DB state.
- Real `run_pipeline()` verification for the Xiaomi example works when the query is passed as a proper Unicode string: the parsed query resolved `entities=['小米集团']`, `time_range={'start': '2025-04-05', 'end': '2026-04-05'}`, and returned non-empty retrieval results (`total_count=35`, `knowledge_units=20`, `event_clusters=45`).
- Earlier empty Xiaomi results were traced to command-line encoding, not retrieval logic: in the current PowerShell heredoc/stdin path, inline Chinese query text may arrive at Python as `????`, which causes the LLM intent parser to see a corrupted query and return empty entities.

---

## 2026-04-05 Full Migration Completion Update

- The legacy compatibility payload in `run_continuous()` has been removed. The public result now only exposes knowledge-base processing metrics, graph sync stats, and errors.
- The legacy compatibility shell in `run_pipeline()` has been removed. The public result now exposes the normalized knowledge retrieval payload plus `timeline_data`, without risk-report style wrapper fields.
- Mainline public outputs no longer include `particles_extracted`, `particles_saved`, `particles`, `particles_count`, `report`, `risk_assessment`, `comparison_report`, or `event_impact`.
- Integration tests now assert the absence of those legacy fields instead of depending on them.
- `docs/STATUS_OVERVIEW.md` and `README.md` are aligned with the actual public interface and no longer imply that legacy output compatibility remains part of the supported mainline.

Full migration is considered complete under the following acceptance conditions:

- `run_continuous()` no longer constructs or returns `particles*`.
- `run_pipeline()` no longer returns risk-report style compatibility fields.
- Mainline implementation no longer constructs `IntelligenceParticle`-style payloads.
- Formal project docs no longer treat the old design as a current interface contract.
- Mainline tests no longer assert the presence of legacy output fields.

- Final naming cleanup is also complete:
  - mainline intent symbols now use `ENTITY_OVERVIEW` and `EVENT_ANALYSIS`
  - routing paths now use `entity_overview_path` and `event_analysis_path`
  - old labels `RISK_ASSESSMENT` / `EVENT_IMPACT` remain only as parser input aliases for backward-compatible intent normalization, not as mainline internal names

---

## 2026-04-05 Graph Retrieval Productization Update

- Graph-aware retrieval is now part of the supported mainline: `run_pipeline(graph_enabled=True)` performs formal graph enhancement over the current `Entity -> INVOLVED_IN -> EventCluster` model instead of only attaching ad hoc edge summaries.
- A dedicated knowledge-graph retrieval service now powers two V1 graph actions:
  - `Entity -> EventCluster` related-event retrieval
  - `Entity -> EventCluster -> Entity` co-involvement expansion
- `run_pipeline()` now keeps the existing public entrypoint while upgrading the output contract:
  - `retrieval` now includes `graph_used`, `graph_candidate_count`, `graph_expanded_cluster_count`, `graph_expanded_entity_count`, and `graph_hit_reasons`
  - `graph` now exposes stable `enabled`, `used`, `nodes`, `edges`, `paths`, and `summary`
- Relationship queries now return formal graph result sets when graph enhancement is enabled, instead of only relying on plain retrieval output plus lightweight edge decoration.
- Graph enhancement is fail-open:
  - Neo4j failure no longer breaks the main retrieval path
  - retrieval continues with knowledge results
  - graph errors are recorded under `errors`
- Regression checks passed after the productization work:
  - `uv run pytest` -> `57 passed`
  - `uv run pyright .` -> `0 errors`
- Follow-up hardening is now in place:
  - graph retrieval no longer attempts Neo4j schema writes on the read path
  - relationship queries over `articles=...` now fail explicitly because graph enhancement is only supported for `knowledge_base`

---

## 2026-04-05 Skill-Facing Contract V1 Update

- Added `src.skills.run_skill_query()` as a stable internal contract over raw retrieval results without changing `run_pipeline()` semantics.
- Skill contract V1 now formally supports three intent families:
  - `ENTITY_OVERVIEW`
  - `ENTITY_TIMELINE`
  - `EVENT_ANALYSIS`
- The V1 envelope is now stable across supported skills:
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
- Source-specific capability normalization is now explicit:
  - `knowledge_base` may report graph support and graph usage
  - `direct_articles` always reports `graph_supported=false` and `graph_used=false`
- Timeline payload normalization is now contractized:
  - cluster-first when `cluster_id` matches a retrieved `EventCluster`
  - graph-expanded `EventCluster` hits are appended even when no selected `KnowledgeUnit` directly carries that `cluster_id`
  - fallback to standalone `KnowledgeUnit` timeline events
  - final event ordering is oldest to newest
- Unsupported V1 intents now return structured contract errors instead of introducing a new caller-visible exception path:
  - `RELATIONSHIP_QUERY`
  - `COMPARATIVE_ANALYSIS`
- Skill contracts now preserve `ok=true` for non-blocking fail-open graph errors while still surfacing those errors in `errors`
- Regression checks passed after the skill-contract work:
  - `uv run pytest tests/unit/test_skill_contract.py`
  - `uv run pytest tests/integration/test_skill_queries.py`
  - `uv run pyright src/skills src/orchestration/__init__.py tests/unit/test_skill_contract.py tests/integration/test_skill_queries.py`

---

## 2026-04-05 Relationship Skill V1 Update

- `run_skill_query()` now formally supports `RELATIONSHIP_QUERY` and returns `skill_type="relationship_query"` instead of treating it as an unsupported intent.
- Added a dedicated relationship payload that keeps graph evidence intact while exposing normalized `related_entities`, `related_event_clusters`, and `relationship_paths` for skill consumers.
- Relationship skill behavior remains aligned with the current pipeline constraints:
  - `run_pipeline()` semantics are unchanged
  - graph fail-open errors still preserve `ok=true` when they are non-blocking `[graph] ...` errors
  - `direct_articles + RELATIONSHIP_QUERY` now returns a stable failed contract shape instead of `unsupported_intent`, preserving `verification` and existing error messages
- Added unit and integration coverage for:
  - successful `knowledge_base` relationship contracts
  - non-blocking graph errors
  - stable failed relationship contracts for `direct_articles`

---

## 2026-04-05 Knowledge Extraction Enhancement Update

### Time Normalization (P0)

- Added `src/time_normalization.py` for event_time standardization:
  - `TimeNormalizer` class converts relative/fuzzy time expressions to absolute datetime
  - Supports Chinese relative time: 昨天、上周X、本周X、N天前、上个月、去年
  - Supports fuzzy time: 近日、近期、今年初、本月末
  - Returns `TimeNormalizationResult` with resolution type and confidence
- Extended `TimeRef` model in `src/knowledge_base.py`:
  - Added `event_time_resolution` field: "absolute" | "relative" | "fuzzy" | "unresolved"
  - Added `raw_event_time_expression` field for source traceability
- Integrated time normalization into `KnowledgeExtractor`:
  - Post-processes LLM-extracted event_time values
  - Normalizes relative times based on document `published_at`

### Conflict Detection (P1)

- Added `src/conflict_detection.py` for multi-source conflict analysis:
  - `ConflictDetector` class detects conflicts across KnowledgeUnits
  - Conflict types: TIME_MISMATCH, AMOUNT_MISMATCH, PARTICIPANT_MISMATCH
  - Extracts monetary amounts from Chinese text (亿元、万美元、港元)
  - Returns `ConflictReport` with severity levels
- Extended `EventCluster` model:
  - Added `conflict_details` field storing structured conflict information
- Integrated conflict detection into `build_event_cluster_snapshot()`:
  - Automatic detection when building cluster aggregates
  - Backward-compatible `multiple_event_time_values` reason preserved

### Regression Checks

- `uv run pytest` -> 96 passed
- `uv run pyright .` -> 0 errors
- New test file: `tests/unit/test_time_normalization.py` (19 tests)

### 2026-04-05 Follow-up Fixes

- `KnowledgeExtractor` now normalizes raw `time.event_time` payloads before `KnowledgeUnit` validation, so relative/fuzzy expressions no longer fail the fail-fast extraction path before normalization can run.
- `ConflictDetector` now treats only explicit `event_time` values as time-conflict evidence; differing `published_at` dates without explicit event dates no longer create false `multiple_event_time_values` cluster conflicts.
- Additive participant mentions are no longer treated as relationship conflicts by default; only contradictory participant deltas across multiple sources produce `participant_mismatch`.
- `run_skill_query()` relationship payloads now return empty `related_entities` / `related_event_clusters` when graph retrieval yields no relationship paths, instead of falling back to unrelated retrieval results.
- Added regression coverage for:
  - pre-validation relative-time normalization
  - no-conflict handling for missing explicit event dates
  - no-conflict handling for additive participant mentions
  - empty relationship-path payload behavior
