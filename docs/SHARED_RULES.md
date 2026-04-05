# 项目共享规范

本文件是 Claude Code 与 Codex 共用的项目级规则真源。涉及项目目标、核心数据契约、图谱设计、离线知识化流程、检索产物、开发约束与进度维护时，统一以本文件为准。

## 1. 项目目标

项目目标：构建一个面向金融场景的知识检索底座，将原始消息加工为可检索、可溯源、可组合的知识层，供后续 skill 驱动的分析 agent 执行通用金融任务。

当前项目重点不是直接产出风险分析报告，而是先完成：

- 原始消息标准化
- 通用知识单元抽取
- 实体与事件归一化
- 图谱构建与更新
- 多索引建库
- 面向 agent 的统一检索底座

风险分析、时间线、主题研究、关系扩展等能力都视为后续消费该底座的 skill，而不是底座本身。

## 2. 核心架构

项目继续保留双模式入口，运行接口语义保持不变：

- `run_continuous(graph_enabled=True)`：离线知识化建库入口
- `run_pipeline(raw_query=\"...\")`：统一知识检索入口

当前阶段的主工作流应聚焦于：

`原始消息 -> 标准化 -> KnowledgeUnit 抽取 -> 实体/时间标准化 -> EventCluster 归并 -> 图谱更新 -> 多索引构建 -> 可检索状态`

其中：

- `run_continuous()` 负责把原始文档推进到可检索状态
- `run_pipeline()` 直接围绕 `KnowledgeUnit`、`Entity`、`EventCluster` 提供检索结果
- 图谱默认开启；除调试、测试或显式禁用外，不应关闭图谱同步与图结果输出

## 3. 核心数据契约

系统第一阶段统一采用四层对象模型：

### 3.1 RawDocument

原始消息对象，表示尚未知识化的输入文档。至少应包含：

- 文档主键
- 标题
- 正文
- 来源
- 发布时间
- URL 或外部引用
- 原始元数据

`RawDocument v1` 字段定义：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_id` | `str` | 是 | 原始文档主键 |
| `source_type` | `str` | 是 | 数据源类型，如 `news` / `announcement` / `filing` / `research` / `brief` |
| `title` | `str` | 是 | 文档标题 |
| `content` | `str` | 是 | 清洗后的正文 |
| `source_name` | `str` | 是 | 来源名称 |
| `published_at` | `datetime` | 是 | 发布时间 |
| `url` | `str \| None` | 否 | 原始链接或外部引用 |
| `language` | `str` | 是 | 语言代码，默认保留标准短码 |
| `market` | `str \| None` | 否 | 市场或区域标识，如 `CN` / `HK` / `US` |
| `tickers` | `list[str]` | 否 | 文档显式提及的证券代码 |
| `authors` | `list[str]` | 否 | 作者或发布主体 |
| `raw_metadata` | `dict[str, Any]` | 否 | 保留原始源头附带元数据 |
| `ingested_at` | `datetime` | 是 | 系统接收时间 |

约束：

- `content` 应保留可供证据切片使用的正文，不应只保留摘要
- `published_at` 与 `ingested_at` 必须分离记录
- 原始源头元数据允许保留，但不得替代标准字段

### 3.2 KnowledgeUnit

`KnowledgeUnit` 是系统的最小可检索证据单元。

主键语义：**来源中的一次陈述**，而不是“事实/事件本体”。

设计原则：

- statement-level 入库
- 证据优先，结论后置
- 必须可溯源
- 必须保留冲突
- 不在抽取阶段过早做激进归并

`KnowledgeUnit v1` 最小字段要求：

- `ku_id`：KnowledgeUnit 主键
- `unit_kind`：`event` 或 `fact`
- `unit_type`：标准化类型，如 `earnings_release`、`executive_change`
- `summary`：标准化摘要
- `entities`：涉及实体，需保留标准实体引用与原始提及
- `source`：来源文档标识与来源信息
- `evidence`：原文证据片段或证据定位
- `time`：事件时间、发布时间、抽取时间
- `confidence`：抽取置信度
- `tags`：事件、主题、行业等标签
- `relation_hints`：可选关系线索
- `cluster_id`：可选，归并后关联的事件簇
- `conflict_status`：`none` / `possible` / `confirmed`

`KnowledgeUnit v1` 推荐字段定义：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ku_id` | `str` | 是 | statement-level 主键，对应一次来源陈述 |
| `unit_kind` | `Literal["event", "fact"]` | 是 | 单元大类 |
| `unit_type` | `str` | 是 | 事件或事实的标准化类型 |
| `summary` | `str` | 是 | 标准化、可检索摘要 |
| `entities` | `list[EntityRef]` | 是 | 涉及实体列表 |
| `source` | `SourceRef` | 是 | 来源文档、来源名称、定位信息 |
| `evidence` | `list[EvidenceSpan]` | 是 | 证据片段列表，至少 1 条 |
| `time` | `TimeRef` | 是 | 事件时间、发布时间、抽取时间 |
| `confidence` | `float` | 是 | 抽取置信度，取值 `0-1` |
| `tags` | `list[str]` | 否 | 行业、主题、事件标签 |
| `relation_hints` | `list[RelationHint]` | 否 | 从文本中抽出的潜在关系线索 |
| `cluster_id` | `str \| None` | 否 | 归并后的事件簇 ID |
| `conflict_status` | `Literal["none", "possible", "confirmed"]` | 是 | 冲突状态 |
| `status` | `Literal["active", "superseded"]` | 是 | 当前证据状态 |

其中：

- `EntityRef` 至少包含：`entity_id | None`、`mention`、`entity_type | None`、`role | None`
- `SourceRef` 至少包含：`doc_id`、`source_name`、`url | None`
- `EvidenceSpan` 至少包含：`text`、`start_offset | None`、`end_offset | None`
- `TimeRef` 至少包含：`event_time | None`、`published_at`、`extracted_at`
- `RelationHint` 至少包含：`relation_type`、`subject_entity_id | None`、`object_entity_id | None`、`confidence`

约束：

- `event_time` 表示事件发生时间，不是报道发布时间
- 任意结论都必须可回溯到 `KnowledgeUnit`
- 发现冲突信息时，必须保留冲突状态，不得静默覆盖
- `evidence` 至少保留一个可读证据片段，禁止只保留抽象总结
- `cluster_id` 可为空，表示尚未归并
- 第一版允许 `entity_id` 为空，但必须保留原始提及 `mention`

### 3.3 EventCluster

`EventCluster` 表示多个 `KnowledgeUnit` 在保守规则下归并后的事件视图。

归并原则：

- 第一版采用保守归并
- 只有在“实体接近、事件类型一致、时间接近、语义高度相似”时才允许归并
- 宁可多簇，不误合并

`EventCluster` 的主要职责：

- 聚合同一事件的多来源证据
- 为图谱和检索提供更稳定的事件节点
- 为下游 skill 提供事件级视图

`EventCluster v1` 字段定义：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `cluster_id` | `str` | 是 | 事件簇主键 |
| `cluster_type` | `str` | 是 | 标准化事件类型 |
| `title` | `str` | 是 | 事件簇标题 |
| `summary` | `str` | 是 | 事件簇摘要 |
| `entity_ids` | `list[str]` | 是 | 关联实体 ID 列表 |
| `primary_entity_id` | `str \| None` | 否 | 主实体 |
| `time_anchor` | `datetime \| date \| None` | 否 | 主时间锚点 |
| `time_range` | `dict[str, Any] \| None` | 否 | 起止时间范围 |
| `member_ku_ids` | `list[str]` | 是 | 成员 `KnowledgeUnit` 列表 |
| `source_doc_ids` | `list[str]` | 是 | 派生来源文档列表 |
| `conflict_status` | `Literal["none", "possible", "confirmed"]` | 是 | 事件簇层冲突状态 |
| `cluster_confidence` | `float` | 是 | 归并置信度，取值 `0-1` |
| `updated_at` | `datetime` | 是 | 最近更新时间 |

归并条件第一版建议同时满足：

- 主实体集合高度重合或可明确映射
- `unit_type` 一致
- 时间窗口足够接近
- `summary` 语义相似度超过阈值
- 不存在明显互斥陈述

以下情况默认不自动合并：

- 同一主体但不同事件阶段
- 同一主题下的连续多次公告
- 信息互相矛盾但尚未判明来源优先级
- 仅依赖模糊名称匹配得出的疑似同事件

### 3.4 Entity

`Entity` 是图谱与检索的标准实体对象。

第一版主实体类型仅支持：

- `Company`
- `Organization`
- `Person`
- `Product`
- `Asset`

以下内容第一版先作为标签或属性，不作为主节点：

- 行业
- 主题
- 地区
- 市场
- 概念板块

实体对齐约束：

- 优先使用证券代码、工商注册号等稳定标识
- 名称模糊匹配只能作为辅助
- 必须保留别名与原始提及

`Entity v1` 字段定义：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entity_id` | `str` | 是 | 标准实体主键 |
| `entity_type` | `Literal["Company", "Organization", "Person", "Product", "Asset"]` | 是 | 实体类型 |
| `canonical_name` | `str` | 是 | 标准名称 |
| `aliases` | `list[str]` | 否 | 别名、简称、外文名 |
| `identifiers` | `dict[str, str]` | 否 | 稳定标识，如证券代码、注册号 |
| `description` | `str \| None` | 否 | 实体简述 |
| `tags` | `list[str]` | 否 | 行业、主题、地区等标签 |
| `source_ku_ids` | `list[str]` | 是 | 支撑该实体建档的知识单元 |
| `created_at` | `datetime` | 是 | 创建时间 |
| `updated_at` | `datetime` | 是 | 最近更新时间 |

实体对齐策略第一版：

- 稳定标识一致时优先直接归一
- 无稳定标识时，以 `canonical_name + alias + context` 保守匹配
- 匹配不确定时，宁可暂不合并，也不生成高风险误归一

## 4. 图谱与 GraphRAG 约定

图谱是 P0 正式产物，不是后续可选增强项。

第一版采用 `Entity + EventCluster` 双核心建模：

- `Entity` 负责承载稳定对象
- `EventCluster` 负责承载聚合后的事件视图
- `KnowledgeUnit` 作为证据层存在，不作为第一版主图检索节点

图谱设计原则：

- 图谱负责结构和连接，不替代证据层
- 所有图节点和边都必须可回溯到底层 `KnowledgeUnit`
- GraphRAG 属于正式检索能力，但必须建立在证据层可验证前提上

第一版推荐边语义包括：

- `Entity -> EventCluster`：参与、触发、涉及
- `EventCluster -> Entity`：影响、作用于
- `Entity -> Entity`：控制、持股、供应、合作等稳定关系
- `EventCluster -> EventCluster`：时间先后、因果或演进关系

## 5. 离线知识化流程

`run_continuous()` 负责离线知识化建库，目标是把原始消息推进到可检索状态。

标准流程：

1. 原始消息接入
2. 文档标准化
3. `KnowledgeUnit` 抽取
4. 实体标准化
5. 时间标准化
6. 去重、冲突保留与保守归并
7. 生成或更新 `EventCluster`
8. 更新图谱
9. 构建或更新多种索引

迁移要求：

- 现有风险导向的 `IntelligenceParticle` 设计视为历史实现，不再作为目标契约
- 不再为旧消费链路保留默认兼容路径；主线实现直接围绕 `KnowledgeUnit` / `EventCluster` / `Entity`
- 禁止继续引入 `v2`、`_legacy_bridge` 这类过渡命名来承载新主线；若旧实现不再适合，应直接删除或用最终命名替换
- `KnowledgeUnit` 抽取默认采用 fail-fast：若 LLM 未配置、调用失败或返回不满足契约，必须直接报错并记录处理失败，不得静默回退到启发式抽取

## 6. 可检索状态定义

“可检索状态”表示一批原始消息已经被加工成可供 agent 与 skill 消费的知识底座。

第一版至少应包含以下正式产物：

- 原始文档库
- `KnowledgeUnit` 库
- `EventCluster` 库
- `Entity` 标准库
- 关键词或稀疏索引
- 向量索引
- 图谱索引

检索系统的职责是让后续 skill 可以稳定地按实体、事件、语义和关系召回证据，而不是只返回文章列表。

## 7. 开发 Guardrails

开发过程中统一遵守：

- 使用 `uv` 管理 Python 环境和依赖
- 不修改运行接口语义：`run_pipeline()`、`run_continuous()`
- 优先补充或复用现有模块，不随意复制逻辑
- 任何“输入 -> 处理 -> 输出”流程都要记录处理状态，成功与失败都可追踪
- 为了暴露缺陷并便于排查，开发默认禁止“未配置/失败后自动回退”这类静默降级；尤其是 `KnowledgeUnit` 抽取，必须失败即暴露
- 图谱在主线实现中默认为开启状态；新增代码不得把“默认关闭图谱”作为常态前提
- 所有图谱更新都必须保留溯源信息
- 所有归并策略默认偏保守
- 对历史风险分析实现的新增改动，不得重新把项目目标收窄为“风险报告系统”

### 7.1 临时文件治理规则

为避免测试、调试、代理执行与手工排查过程污染项目目录，统一遵守以下约束：

- 所有临时文件、缓存目录、调试产物默认收口到仓库内隐藏目录 `.tmp/`
- 不允许在项目根目录新增随机命名的临时目录；如 `pytest-cache-files-*`、`tmp*`、`codex_pytest_review_*`、`codex-pytest-*`
- 测试工具必须显式配置缓存目录、临时基目录与测试发现范围，避免扫描或创建根目录临时产物
- 新增脚本、工具接入或 agent 工作流时，如会写入中间产物，必须优先写入 `.tmp/`，并同步补充 `.gitignore`
- 历史残留的临时目录应通过仓库内统一清理脚本或明确治理动作处理，不应长期保留在项目根目录
- 除排查权限或占用问题外，不应依赖操作系统用户目录或桌面目录作为默认临时产物位置

### 7.2 Legacy 隔离规则

以下规则用于明确历史设计的边界，避免已弃用方案重新回流到知识底座主线：

- `IntelligenceParticle`、`RiskReport`、旧风险图查询语义统一视为已弃用的 `legacy` 设计
- 新功能不得继续以 `IntelligenceParticle` 作为核心数据契约扩展
- 新功能不得以 `RiskReport` 作为默认输出目标扩展
- 新检索、图谱、知识化逻辑必须优先围绕 `RawDocument`、`KnowledgeUnit`、`EventCluster`、`Entity` 设计
- 不再为旧消费链路维持主线路径兼容；若旧实现未被新主线使用，应优先删除，而不是继续保留为事实上的现行设计
- 运行入口 `run_continuous()`、`run_pipeline()` 的接口语义保持不变，但其内部实现允许逐步切换到新架构

推荐迁移分层：

- 新实现优先落在最终命名模块，如 `knowledge`、`entities`、`clustering`、`indexing`、`retrieval`
- 新模块禁止把旧风险模型当作一等公民继续传播

验收补充要求：

- 新增代码不得无必要扩大对旧风险模块的依赖范围
- 新增知识化逻辑必须能在不引入 `RiskReport` 的前提下独立成立
- 新增图谱与检索逻辑必须以 `KnowledgeUnit` 可回溯为前提

## 8. 测试与验收

基础检查命令：

```bash
uv run pytest
uv run pyright .
```

当前阶段验收重点：

- 双模式入口可正常调用
- `run_continuous()` 可以稳定推进离线知识化流程
- 核心对象从原始文档到 `KnowledgeUnit`、`EventCluster`、`Entity` 的迁移路径清晰
- 图谱更新结果可回溯到底层 `KnowledgeUnit`
- 文档引用统一指向本文件，不再把旧风险导向描述当项目真源

## 9. 进度维护

完成任何功能开发后，必须同步更新 `PROGRESS.md`：

- 更新对应模块的完成状态
- 补充新增能力或约束
- 若新增的是项目级规则，也要同时回写到本文件

## 10. 文档分层

- `docs/SHARED_RULES.md`：项目级唯一真源
- `PROGRESS.md`：当前状态、迁移进度与待办
- `README.md`：外部入口与高层说明
- `AGENTS.md`：Codex 入口
- `CLAUDE.md`：Claude Code 入口
- `.claude/rules/`：Claude 机制适配层与历史专题规则

如果多个文档表述不一致，优先级如下：

1. `docs/SHARED_RULES.md`
2. 代码中的真实实现
3. `PROGRESS.md`
4. `README.md`
5. `AGENTS.md` / `CLAUDE.md` / `.claude/rules/`
