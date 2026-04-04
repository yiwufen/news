# 项目开发进度

## 双模式架构

系统采用"生产-消费"双模式架构：

| 模式 | 目标 | 入口 | 数据流向 |
|------|------|------|----------|
| **持续运行** | 新闻 → 情报微粒 | `WorkerAgent.run()` | 生产数据 |
| **任务驱动** | 用户查询 → 分析报告 | `run_pipeline()` | 消费数据 |

**关键设计**：任务驱动模式直接检索持续运行模式产出的情报微粒，无需重新提取。

---

## 当前状态概览

| 层级 | 状态 | 完成度 | 说明 |
|------|------|--------|------|
| 2.0 意图解析层 | ✅ 已完成 | 100% | IntentClassifier、时间解析、实体提取均已实现 |
| 2.1 检索层 | ⚠️ 部分实现 | 50% | 元数据过滤已实现，BM25/向量检索为预留接口 |
| 2.2 并行提炼层 | ✅ 已完成 | 100% | Worker Agent 可运行 |
| 2.3 动态记忆层 | ✅ 已完成 | 100% | SQLite + Neo4j 均已实现 |
| 2.4 宏观研判层 | ✅ 已完成 | 100% | Master/Critic Agent 可运行 |
| 2.5 编排调度层 | ✅ 已完成 | 100% | LangGraph 状态机已实现，支持按意图路由 |

---

## 已实现功能

### 意图解析层
- [x] IntentType 枚举定义 (`src/intent/models.py`)
- [x] StructuredQuery 数据模型
- [x] TimeRange 时间范围解析
- [x] QueryFilters 过滤条件
- [x] IntentClassifier 意图分类器 (`src/intent/classifier.py`)
- [x] LLM 驱动的意图解析
- [x] 相对/绝对时间表达式解析

### 检索层
- [x] ParticleSearcher 情报微粒检索器 (`src/retrieval/particle_search.py`)
- [x] HybridSearcher 文章检索器 (`src/retrieval/hybrid_search.py`)
- [x] 元数据过滤 (时间范围、实体、事件类型)
- [x] 实体关键词过滤
- [x] 检索节点回退机制 (微粒 → 文章)

### 持续运行模式入口
- [x] ContinuousPipeline 完整流水线 (`src/pipeline/continuous.py`)
- [x] Worker Agent 提取情报微粒
- [x] Integrator Agent 图谱同步
- [x] 处理状态追踪
- [ ] BM25 检索 (预留接口)
- [ ] 向量检索 (预留接口)
- [ ] RRF 融合 (待实现)

### 数据采集与存储
- [x] SQLite 数据库管理 (`collectors/database.py`)
- [x] 新闻文章存储 (80 篇测试数据)
- [x] 情报微粒存储
- [x] 处理状态追踪

### Worker Agent
- [x] 单篇/批量情报提取 (`src/agents/worker/agent.py`)
- [x] LLM Tool Use 结构化输出
- [x] 嵌套 JSON 解析修复 (兼容百度千帆 API)
- [x] 增量处理支持
- [x] 时间切片分组

### 风险计算引擎
- [x] 风险传导公式实现 (`src/risk/calculator.py`)
- [x] 时间衰减计算
- [x] 路径权重计算
- [x] 风险评估模型

### 图谱模块
- [x] Neo4j 连接管理 (`src/graph/connection.py`)
- [x] Cypher 查询模板 (`src/graph/queries.py`)
- [x] 风险穿透查询
- [x] 特殊风险模式检测 (环形担保、链式担保)

### Agent 编排
- [x] LangGraph 状态图 (`src/orchestration/graph.py`)
- [x] 节点函数封装 (`src/orchestration/nodes.py`)
- [x] 状态定义 - PipelineContext 上下文对象 (`src/orchestration/state.py`)
- [x] Pipeline 入口 - `run_pipeline()` 函数

### 意图路由
- [x] 5 种意图路径：ENTITY_TIMELINE, RISK_ASSESSMENT, RELATIONSHIP_QUERY, COMPARATIVE_ANALYSIS, EVENT_IMPACT
- [x] `comparative_analysis_node` 多实体对比分析
- [x] `event_impact_node` 事件影响分析
- [x] 单元测试 + 集成测试 (38 个测试)

---

## 待开发功能

### 优先级 P0：检索层增强

- [ ] 实现真正的 BM25 检索 (当前为简单关键词匹配)
- [ ] 实现向量检索
- [ ] 实现 RRF 融合算法
- [ ] 建立实体别名词典

### 基础设施

- [x] Neo4j 实例部署
- [ ] 配置向量数据库
- [ ] 创建文章嵌入索引
- [ ] 批量向量化历史文章

### 优先级 P2：增强功能

- [ ] 重排序模型 (Cross-Encoder)
- [ ] 多轮对话支持
- [ ] 报告导出 (PDF/Markdown)
- [ ] API 接口封装

---

## 技术选型建议

### 向量数据库
| 选项 | 优点 | 缺点 |
|------|------|------|
| Qdrant | 高性能、支持过滤、云原生 | 需要部署 |
| Milvus | 分布式、企业级 | 较重 |
| FAISS | 本地运行、简单 | 不支持过滤 |

**建议**：开发阶段使用 FAISS，生产环境迁移 Qdrant。

### BM25 引擎
| 选项 | 优点 | 缺点 |
|------|------|------|
| rank_bm25 | 纯 Python、简单 | 不支持持久化 |
| Elasticsearch | 企业级、分布式 | 需要部署 |

**建议**：开发阶段使用 rank_bm25 + SQLite 全文搜索。

---

## 测试数据状态

```
数据库: data/news.db
├── 文章数: 80
├── 情报微粒数: 4
├── 处理成功: 4
└── 处理失败: 32 (需重新处理)

时间范围: 2026-01-02 ~ 2026-03-30
分类分布:
  - SUPPLY_CHAIN: 20
  - CORPORATE_MERGER: 17
  - FINANCIAL_EARNINGS: 14
  - POLICY_SANCTION: 10
  - TARIFF_TRADE: 7
  - REGULATORY_ACTION: 5
  - MARKET_VOLATILITY: 6
```

---

## 运行方式

### 模式一：持续运行模式

```bash
# 完整流程：新闻 → 情报微粒 → 图谱同步
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.pipeline import run_continuous

result = run_continuous(
    batch_size=10,
    graph_enabled=True,   # 启用图谱同步
    incremental=True,     # 只处理未处理的文章
)
print(f'情报微粒: {result.particles_extracted}')
print(f'图谱节点: {result.nodes_created}')
print(f'图谱关系: {result.edges_created}')
"

# 无 Neo4j 环境时，可禁用图谱同步
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=False)
print(f'情报微粒: {result.particles_extracted}')
"
```

### 模式二：任务驱动模式

```bash
# 自然语言查询 → 检索情报微粒 → 生成报告
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=False  # 无图谱模式
)
print(result)
"
```

### 其他测试

```bash
# 测试意图解析
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.intent import IntentClassifier

classifier = IntentClassifier()
query = classifier.parse('查看小米集团过去一年做的事情')
print(query.to_dict())
"

# 测试情报微粒检索
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.retrieval import ParticleSearcher, ParticleRetrievalRequest
from src.intent.models import StructuredQuery, IntentType

searcher = ParticleSearcher()
result = searcher.search(ParticleRetrievalRequest(
    structured_query=StructuredQuery(
        intent=IntentType.ENTITY_TIMELINE,
        entities=['小米集团'],
    ),
))
print(f'检索到 {result.total_count} 个情报微粒')
"
```

### 注意事项

- 持续运行模式需要先运行，产出情报微粒后任务驱动模式才能检索
- 若无情报微粒，任务驱动模式会回退到原始文章检索
- 完整流水线需要配置 LLM API (百度千帆或 Anthropic)

---

## 相关文档

- [CLAUDE.md](CLAUDE.md) - 项目架构与开发规则
- [.claude/rules/01-taxonomy.md](.claude/rules/01-taxonomy.md) - 金融语义标准
- [.claude/rules/02-prompts.md](.claude/rules/02-prompts.md) - Agent Prompt 模板
- [.claude/rules/03-risk-logic.md](.claude/rules/03-risk-logic.md) - 风险传导算法
- [.claude/rules/04-intent-retrieval.md](.claude/rules/04-intent-retrieval.md) - 意图解析与检索规范
