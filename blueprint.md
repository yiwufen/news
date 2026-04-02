这是一份为您量身定制的完整项目技术文档，可直接作为开发团队的全局架构指南（Blueprint）。

---

# 研发指南：AI Agent 驱动的情报分析系统

**文档版本：** V1.0 (Demo及一期演进版)
**目标读者：** 架构师、后端研发工程师、AI/Prompt 工程师
**核心愿景：** 解决海量非结构化情报处理中的“上下文溢出”、“逻辑幻觉”与“高昂 Token 成本”问题，构建高可用、可溯源的自动化研判流水线。

---

## 1. 核心架构思想 (Core Philosophy)

本系统摒弃了传统的“单体 Agent 串行阅读”模式，采用 **“漏斗过滤 + 时间切片并行压缩 (Map-Reduce) + 实体锚定”** 的设计范式。



* **漏斗过滤 (Funneling)：** 绝不在海量噪声数据上浪费大模型算力，通过低成本检索层进行硬性拦截。
* **并行压缩 (Map-Reduce)：** 将时间线切片，通过 Worker Agent 集群并行提取信息，将长文本压缩为高密度的“情报微粒（JSON）”，再交由 Master Agent 进行全局推演。
* **实体锚定 (Entity-First)：** 检索和关联的核心是“实体（人、组织、标的）”，而非宽泛的语义动作。

---

## 2. 系统分层架构 (System Architecture Layers)

系统通过状态机（State Machine）框架进行编排，分为四个解耦的层级：

### 2.1 任务接入与预过滤层 (Ingestion & Pre-filtering)
**职责：** 接收自然语言任务，执行粗筛，生成“任务专属数据池”。
* **Query Rewrite (查询重写)：** 将用户输入转化为实体词典和多维度检索式（同义词、行业黑话扩展）。
* **Hybrid Search (混合检索)：** * **向量检索 (Dense)：** 捕获语义相关性（如：“打压”与“制裁”对齐）。
    * **字面检索 (Sparse/BM25)：** 强制精确匹配实体代号（如：“Project X-99”）。
* **Metadata Filtering (元数据硬过滤)：** 根据时间戳、信息源可靠度、实体标签进行前置 SQL/DSL 过滤。

### 2.2 并行提炼层 (Map Layer - The Workers)
**职责：** 并行处理切片数据，执行信息抽取（Information Extraction, IE）。
* **Time-Window Slicer：** 将召回的数千篇候选池文档，严格按时间窗口（如按周、按月）切片。
* **Worker Agent 集群：** 为每个时间切片分配独立的 Agent 实例。
    * *输入：* 单个时间切片内的 50-100 篇新闻。
    * *输出：* 强制结构化输出“情报微粒（Intelligence Particle）”。

### 2.3 动态记忆层 (Memory & Persistence)
**职责：** 系统的“公共白板”，存储高度压缩后的结构化情报。
* **结构化存储：** 采用 PostgreSQL (JSONB) 或 MongoDB，按时间序列存储 Worker Agent 提炼的微简报。
* **图谱映射准备：** 存储提取出的 `主-谓-宾` 三元组，为后续演进到 GraphRAG 提供底层数据支撑。

### 2.4 宏观研判层 (Reduce Layer - The Master)
**职责：** 全局推理、防幻觉校验与报告渲染。
* **Master Analyst Agent：** 按时间序列读取数据库中的“情报微粒”，进行跨周期逻辑推理（如发现产业制裁趋势的转移）。
* **Critic Agent (红蓝对抗)：** 事实核查员，对比最终报告与原始情报微粒，驳回无引用依据的“幻觉”结论。
* **Citation Engine (溯源引擎)：** 强制在最终报告的每一句断言后附带原始 `doc_id` 锚点。

---

## 3. 核心数据契约：情报微粒 (Intelligence Particle Schema)

**开发强制规范：** Worker Agent 的节点代码中，**必须**使用大模型 API 的 `Structured Output (JSON Mode)` 绑定此 Schema，严禁依赖纯 Prompt 控制输出格式。

```json
{
  "particle_id": "evt_uuid",
  "time_context": {
    "slice_window": "2026-W10",         
    "exact_event_date": "2026-03-05"    // 提取出的确切事件发生日期
  },
  "core_event": {
    "event_type": "POLICY_SANCTION",    // 需对齐预设的 Enum 字典
    "event_summary": "某国宣布限制向 A 企业出口下一代 EUV 光刻机组件。", 
    "auto_tags": ["出口管制", "供应链", "EUV"] 
  },
  "entities_and_relations": {
    "entities": [
      {"name": "某国政府", "type": "GOVERNMENT", "role": "ACTOR"},
      {"name": "A 企业", "type": "COMPANY", "role": "TARGET"},
      {"name": "EUV组件", "type": "TECHNOLOGY", "role": "OBJECT"}
    ],
    "triplets": [
      {"subject": "某国政府", "predicate": "RESTRICT_EXPORT", "object": "A 企业"}
    ]
  },
  "intelligence_metrics": {
    "impact_level": "CRITICAL",         // CRITICAL, HIGH, MEDIUM, LOW
    "sentiment": "NEGATIVE",            // 利好或利空
    "credibility_score": 0.85           // 基于交叉印证度量
  },
  "traceability": {
    "source_doc_ids": ["doc_1024", "doc_1029"], 
    "is_contradictory": false           // 切片内是否发现冲突情报
  }
}
```

---

## 4. 进阶检索链路 (Advanced Retrieval Pipeline)

对于存量历史数据的深挖，必须实现以下四步标准流水线（Agentic RAG）：

1.  **意图拆解：** 用户指令 -> 提取“实体集合” + “时间边界” + “行为动词”。
2.  **双路召回 (Hybrid)：** * Query 1 (实体): 执行 BM25 关键字检索。
    * Query 2 (动词/意图): 执行 Vector Dense 语义检索。
3.  **倒数排名融合 (RRF)：** 合并双路召回结果，进行初步去重与平滑打分。
4.  **二次重排 (Cross-Encoder Re-ranking)：** 引入重排模型（如 BGE-Reranker），对比原问题与召回 Chunk，输出最终的 Top-K 进入候选池。

---

## 5. 技术栈与选型建议 (Tech Stack Selection)

* **多智能体编排框架：** **LangGraph** (首选，其状态图 DAG 机制极度契合 Map-Reduce 的多节点并发与循环回退)。
* **混合检索与向量库：** **Qdrant** 或 **Milvus** (原生支持 Dense + Sparse 双路混合与复杂的 Metadata 过滤)。
* **状态与微粒数据库：** **PostgreSQL** (极度推荐，利用其 JSONB 字段存储情报微粒，且支持成熟的并发读写)。
* **模型路由策略 (Model Cascading)：**
    * *Worker Agents (高并发/信息提取)：* 调用 DeepSeek-V3、Claude 3.5 Haiku 或本地部署的 Llama-3 (14B/70B)。核心诉求：快、便宜、JSON 输出稳定。
    * *Master & Critic Agents (深层逻辑/报告渲染)：* 调用 GPT-4o 或 Claude 3.5 Sonnet。核心诉求：极致的逻辑推理能力与长文本驾驭力。

---

## 6. 开发排雷指南 (Engineering Guardrails)

1.  **防御“中间遗忘”：** 严格限制 Worker Agent 每次吞吐的 Token 量。切片过大时，应继续缩短时间窗口（如从“按周”降级为“按天”）。
2.  **处理情报冲突：** 当 `is_contradictory` 字段为 `true` 时，Master Agent 不得执行主观过滤，必须在最终报告中明确展示冲突的双边观点（如：“针对此事，路透社与彭博社信源存在分歧...”）。
3.  **死循环熔断：** 在 LangGraph 的图中，针对 Critic Agent（核查打回）节点，必须设置 `max_retries` 上限（通常设为 2 次）。超过次数依然不通过的，按“置信度不足”降级输出，防止 Token 无限消耗。