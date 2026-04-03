# 项目开发规则

## 项目愿景 (The Vibe)

构建一个 **AI Agent 驱动的金融风险雷达**。系统通过分析非结构化公告，自动构建"公司-债务-担保"关系图谱，并能通过图路径自动发现 A 暴雷后对底层资产 B 的风险传导。

**核心愿景：** 解决海量非结构化情报处理中的"上下文溢出"、"逻辑幻觉"与"高昂 Token 成本"问题，构建高可用、可溯源的自动化研判流水线。

---

## 核心架构思想 (Core Philosophy)

本系统摒弃了传统的"单体 Agent 串行阅读"模式，采用 **"漏斗过滤 + 时间切片并行压缩 (Map-Reduce) + 实体锚定"** 的设计范式。

* **漏斗过滤 (Funneling)：** 绝不在海量噪声数据上浪费大模型算力，通过低成本检索层进行硬性拦截。
* **并行压缩 (Map-Reduce)：** 将时间线切片，通过 Worker Agent 集群并行提取信息，将长文本压缩为高密度的"情报微粒（JSON）"，再交由 Master Agent 进行全局推演。
* **实体锚定 (Entity-First)：** 检索和关联的核心是"实体（人、组织、标的）"，而非宽泛的语义动作。

---

## 技术栈选型 (Tech Stack)

* **Language:** Python 3.13+
* **环境管理:** 使用 `uv` 管理 Python 环境和依赖
* **Orchestration:** LangGraph (Stateful Multi-agent)
* **Database:** Neo4j (Graph), PostgreSQL (Structured Logs)
* **Search:** Qdrant 或 Milvus (Dense + Sparse 双路混合检索)
* **Models:**
    * `glm-5` (Master Reasoning - 深层逻辑/报告渲染)
    * `gpt-4o-mini` 或 `deepseek-v3` (Worker Extraction - 高并发/信息提取)

---

## 系统分层架构 (System Architecture Layers)

系统通过状态机（State Machine）框架进行编排，分为四个解耦的层级：

### 2.1 任务接入与预过滤层 (Ingestion & Pre-filtering)
**职责：** 接收自然语言任务，执行粗筛，生成"任务专属数据池"。
* **Query Rewrite (查询重写)：** 将用户输入转化为实体词典和多维度检索式（同义词、行业黑话扩展）。
* **Hybrid Search (混合检索)：**
    * **向量检索 (Dense)：** 捕获语义相关性（如："打压"与"制裁"对齐）。
    * **字面检索 (Sparse/BM25)：** 强制精确匹配实体代号（如："Project X-99"）。
* **Metadata Filtering (元数据硬过滤)：** 根据时间戳、信息源可靠度、实体标签进行前置 SQL/DSL 过滤。

### 2.2 并行提炼层 (Map Layer - The Workers)
**职责：** 并行处理切片数据，执行信息抽取（Information Extraction, IE）。
* **Time-Window Slicer：** 将召回的数千篇候选池文档，严格按时间窗口（如按周、按月）切片。
* **Worker Agent 集群：** 为每个时间切片分配独立的 Agent 实例。
    * *输入：* 单个时间切片内的 50-100 篇新闻。
    * *输出：* 强制结构化输出"情报微粒（Intelligence Particle）"。

### 2.3 动态记忆层 (Memory & Persistence)
**职责：** 系统的"公共白板"，存储高度压缩后的结构化情报。
* **结构化存储：** 采用 PostgreSQL (JSONB) 存储情报微粒，按时间序列存储。
* **图谱映射准备：** 存储提取出的 `主-谓-宾` 三元组，为 GraphRAG 提供底层数据支撑。

### 2.4 宏观研判层 (Reduce Layer - The Master)
**职责：** 全局推理、防幻觉校验与报告渲染。
* **Master Analyst Agent：** 按时间序列读取数据库中的"情报微粒"，进行跨周期逻辑推理。
* **Critic Agent (红蓝对抗)：** 事实核查员，对比最终报告与原始情报微粒，驳回无引用依据的"幻觉"结论。
* **Citation Engine (溯源引擎)：** 强制在最终报告的每一句断言后附带原始 `doc_id` 锚点。

---

## 核心数据契约：情报微粒 (Intelligence Particle Schema)

**开发强制规范：** Worker Agent 的节点代码中，**必须**使用大模型 API 的 `Structured Output (JSON Mode)` 绑定此 Schema，严禁依赖纯 Prompt 控制输出格式。

```json
{
  "id": "string (uuid)",
  "metadata": {
    "source": "string (file_name/url)",
    "event_time": "ISO-8601",
    "reliability": "float (0-1)"
  },
  "risk_signal": {
    "type": "string (DEBT_DEFAULT | EQUITY_PLEDGE | RESTRUCTURING | LEGAL_SUIT)",
    "level": "string (CRITICAL | HIGH | MEDIUM | LOW)",
    "description": "string"
  },
  "graph_updates": {
    "nodes": [
      {"id": "string", "label": "string", "type": "COMPANY | PERSON | ASSET"}
    ],
    "edges": [
      {
        "source": "string",
        "target": "string",
        "relation": "string (OWNS | GUARANTEES | DEBTOR_OF)",
        "properties": {"amount": "number", "percent": "float"}
      }
    ]
  },
  "traceability": {
    "source_doc_ids": ["doc_1024", "doc_1029"],
    "is_contradictory": false
  }
}
```

---

## 图谱 Schema (Neo4j)

### Nodes
`Company`, `Person`, `FinancialProduct`, `RiskEvent`

### Edges
* `(:Company)-[:INVESTS {percent}]->(:Company)`
* `(:Company)-[:GUARANTEES {amount}]->(:Company)`
* `(:Company)-[:ISSUES]->(:FinancialProduct)`
* `(:RiskEvent)-[:OCCURRED_AT]->(:Company)`

---

## Agent 流水线逻辑 (The Flow)

使用 **LangGraph** 编排以下三个节点，形成循环状态机：

### 节点 A：Worker Agent (The Extractor)
* **输入：** 原始文本片段。
* **指令：** "从文本中识别金融主体和风险事件。特别注意'担保'和'实际控制人'关系。输出格式必须为上面的 Intelligence Particle JSON。"
* **防御逻辑：** 如果文本中没有明确的金融风险，返回空对象，不要脑补。

### 节点 B：Integrator Agent (The Graph Sync)
* **输入：** Intelligence Particle。
* **指令：** "执行实体对齐（Entity Resolution）。查询数据库中是否存在同名公司，若存在则合并 ID。将 nodes 和 edges 写入 Neo4j。"
* **规则：** 所有的边必须带上 `valid_from` 时间戳。

### 节点 C：Master Agent (The Risk Miner)
* **输入：** 分析师查询（例如："查询 X 产品的底层穿透风险"）。
* **指令：** "执行 Cypher 查询，搜索该产品向下 3 层的关系路径。寻找路径中是否存在已标记为 `RiskEvent` 的节点。"
* **核心算法：** 风险分值 = Σ(源风险分 × 传导系数)
    * *传导系数参考：* 控股 (0.9), 担保 (0.8), 业务往来 (0.3)

---

## 规则文件索引 (Rules Index)

以下规则文件位于 `.cursor/rules/` 目录，按场景自动关联：

| 文件 | 用途 | 关联场景 |
|------|------|----------|
| [01-taxonomy.md](.claude/rules/01-taxonomy.md) | 金融语义与枚举标准 | 事件分类、关系定义、风险等级 |
| [02-prompts.md](.claude/rules/02-prompts.md) | Agent System Prompt 模板 | Worker/Integrator/Master/Critic Agent |
| [03-risk-logic.md](.claude/rules/03-risk-logic.md) | 风险传导算法与数学公式 | 风险计算、路径搜索、Cypher 查询 |

---

## 开发约束与规则 (Guardrails)

### 环境管理

使用 `uv` 管理 Python 环境和依赖。

### 类型检查

提交前执行 `uv run pyright .` 确保无类型错误。

### 数据处理状态追踪

任何涉及"输入 → 处理 → 输出"的流程，必须：

1. **记录处理状态**：每个输入项必须有明确的处理状态
2. **即时持久化**：成功的输出应立即保存，而非批量积累后保存
3. **独立于输出**：处理状态记录独立于输出结果

| 状态 | 说明 |
|------|------|
| success | 成功处理，关联输出 ID |
| failed | 处理失败，记录错误原因 |
| pending | 待处理（可选） |

**反模式：**
- ❌ 用输出反推处理状态（如用 particle.source_doc_ids 判断文章是否处理过）
- ❌ 批量积累后一次性保存
- ❌ 处理失败只打印日志，不记录状态

### 实体对齐准则 (Entity Alignment)

必须实现一个 `normalize_entity_name` 函数：
* **规则：** 移除"有限公司"、"股份公司"等后缀进行模糊匹配。
* **优先级：** 如果有工商注册号（Unified Social Credit Code），以此为唯一键。

**实体消歧实现逻辑：**
1. **模糊匹配阈值：** 两个 `Company` 节点名称模糊匹配度 > 90%，且没有冲突的工商号 → 在 Integrator Agent 阶段自动合并。
2. **工商号优先：** 如果存在工商号，以工商号为唯一主键，名称差异不触发合并。
3. **冲突处理：** 名称相似但工商号不同 → 保留为独立节点，记录"疑似关联"标签。

### 时序逻辑准则 (Temporal Logic)

* **规则：** 所有的风险推演必须基于"事件时间线"。
* **错误预防：** 禁止使用发生时间在 T2 的事件去预警 T1 的风险。

### 防幻觉指令 (Anti-Hallucination)

* **指令：** 在生成最终报告时，每一个风险点后面必须紧跟 `[Source: Particle_ID]`。如果 AI 找不到来源，必须承认"证据不足"。

### 处理情报冲突

当 `is_contradictory` 字段为 `true` 时，Master Agent 不得执行主观过滤，必须在最终报告中明确展示冲突的双边观点。

### 死循环熔断

在 LangGraph 的图中，针对 Critic Agent（核查打回）节点，必须设置 `max_retries` 上限（通常设为 2 次）。超过次数依然不通过的，按"置信度不足"降级输出。

### 防御"中间遗忘"

严格限制 Worker Agent 每次吞吐的 Token 量。切片过大时，应继续缩短时间窗口（如从"按周"降级为"按天"）。

---

## 进阶检索链路 (Advanced Retrieval Pipeline)

对于存量历史数据的深挖，必须实现以下四步标准流水线（Agentic RAG）：

1. **意图拆解：** 用户指令 -> 提取"实体集合" + "时间边界" + "行为动词"。
2. **双路召回 (Hybrid)：**
    * Query 1 (实体): 执行 BM25 关键字检索。
    * Query 2 (动词/意图): 执行 Vector Dense 语义检索。
3. **倒数排名融合 (RRF)：** 合并双路召回结果，进行初步去重与平滑打分。
4. **二次重排 (Cross-Encoder Re-ranking)：** 引入重排模型，对比原问题与召回 Chunk，输出最终的 Top-K 进入候选池。
