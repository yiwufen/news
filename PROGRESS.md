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
| 2. 文档知识化抽取 | ⚠️ 迁移中 | 70% | `run_continuous()` 已切到 `RawDocument -> KnowledgeUnit` 新主线，抽取仍以启发式/最小 LLM 契约为主 |
| 3. 实体与事件归一 | ⚠️ 迁移中 | 65% | 已新增 `Entity` / `EventCluster` 保守归一与归并，但规则仍需继续增强 |
| 4. 检索层 | ⚠️ 部分实现 | 40% | 基础过滤和回退已实现，正式 BM25/向量/统一重排仍缺失 |
| 5. 图谱层 | ⚠️ 迁移中 | 65% | 新离线路径已同步 `Entity + EventCluster + INVOLVED_IN`，旧查询层仍保留风险导向实现 |
| 6. 任务消费层 | ⚠️ 暂保留 | 30% | 现有 `run_pipeline()` 可运行，但属于旧风险导向消费逻辑 |

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
- [x] LangGraph 编排骨架
- [x] 阶段状态与错误追踪

### 抽取与图谱基础设施
- [x] Worker Agent 结构化抽取能力
- [x] Integrator Agent 图谱同步能力
- [x] Neo4j 连接管理
- [x] 基础 Cypher 查询模板

### 基础检索
- [x] 文章检索器骨架
- [x] 结构化过滤基础能力
- [x] 微粒到文章的回退机制

### 测试与工程
- [x] 单元测试与集成测试骨架
- [x] `uv` 环境与依赖管理
- [x] `pyright` 类型检查接入
- [x] `uv` 本地缓存目录固定为仓库内 `.uv-cache/`，避免用户目录缓存异常影响 `uv run`

---

## 明确需要迁移或降级的旧设计

以下内容仍存在于代码中，但不再代表目标架构：

- [ ] `IntelligenceParticle` 作为核心数据契约
- [ ] `risk_signal` 作为抽取层强制中心字段
- [ ] `RiskReport` 作为默认终点产物
- [ ] “风险研判系统”作为项目定位
- [ ] 以风险传导为中心的图查询语义

这些能力后续应降级为某些 skill 的消费逻辑，而不是知识底座本身。

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
- [ ] 建立冲突保留与多来源聚合逻辑
- [x] 建立可追踪的离线知识化状态记录
- [x] 修复知识化主线稳定性问题：`ku_id` 可重放、图同步失败可重试、legacy 回填仅保留明确可映射事件

### 图谱与 GraphRAG
- [x] 按 `Entity + EventCluster` 重构新离线路径图谱主模型
- [x] 定义节点、边与溯源约束
- [ ] 让图谱成为正式可检索产物
- [x] 保证图结果可回溯到底层 `KnowledgeUnit`

### 检索系统
- [ ] 建立 `KnowledgeUnit` 稀疏索引
- [ ] 建立 `KnowledgeUnit` 向量索引
- [ ] 建立 `Entity` 与 `EventCluster` 检索入口
- [ ] 定义统一检索返回契约
- [ ] 实现 BM25 / 向量检索 / 融合排序

---

## P1 后续任务

- [ ] 设计面向 skill 的统一检索接口
- [ ] 将风险分析改造为消费知识底座的 skill
- [ ] 将时间线生成功能改造为消费知识底座的 skill
- [ ] 支持主题研究、关系扩展、事件影响分析 skill
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
load_dotenv()
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=False)
print(result)
"
```

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=False,
)
print(result)
"
```

说明：

- 上述入口当前仍可运行
- 但 `run_pipeline()` 代表的是迁移期旧消费层，不代表项目最终目标形态
- 当前研发重点应优先放在 `run_continuous()` 驱动的离线知识化建库

---

## 相关文档

- [docs/SHARED_RULES.md](docs/SHARED_RULES.md) - 项目共享规范真源
- [README.md](README.md) - 项目入口说明
- [AGENTS.md](AGENTS.md) - Codex 入口
- [CLAUDE.md](CLAUDE.md) - Claude Code 入口

项目级规则统一以 `docs/SHARED_RULES.md` 为准。
