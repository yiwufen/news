# 检索底座准确性设计缺陷分析

> 分析日期：2026-04-09
> 分析范围：检索准确性（不含数据增长相关的性能问题）
> 分析状态：进行中

## 当前检索架构

```
用户查询 → IntentClassifier → StructuredQuery
  → KnowledgeSearcher.search()
    → find_by_names() 解析实体
    → search_bm25() FTS5 全文搜索
    → _build_ranked_result() 分层打分重排
    → 补充关联 Entity + EventCluster
  → graph.py 图谱增强（可选）
```

核心打分策略：实体匹配(5.0) > 事件类型(2.0) > BM25 文本分 > 时效(tiny)

---

## P0 缺陷

### 缺陷 1：实体解析硬门——匹配失败直接返回空

**位置**：`src/retrieval/knowledge_search.py:85-86`

```python
if query.entities and not entity_id_filter:
    return self._empty_result(request, matched_entities)
```

**问题**：意图解析提取到实体名（如"小米集团"），但 `find_by_names()` 在数据库中未找到对应 entity_id 时，检索直接返回空——不会退化为纯文本搜索。

**触发场景**：
- 实体尚未入库（新上市、新报道的公司/人物）
- 跨语言异构名称（"BYD" vs 数据库中的"比亚迪"）
- 查询中其他有效信号（事件类型、时间范围）全部被丢弃

**根因**：无退化搜索策略，"无实体就无结果"过于激进。

**影响面**：所有包含实体但实体未入库的查询。

---

### 缺陷 2：event_type 词表断层——查询端和索引端无共享词表

**位置**：
- 查询端：`src/intent/classifier.py` LLM 自由返回 event_types
- 索引端：`src/knowledge_base.py` KnowledgeUnit.unit_type 由另一轮 LLM 抽取确定

**问题**：两个 LLM 调用之间没有共享词表。

**示例**：
- LLM（查询端）返回 `["equity_pledge"]`
- 数据库存的是 `"股权质押"`
- SQL `unit_type IN ('equity_pledge')` → 匹配 0 条

**关键影响**：event_type 过滤发生在 BM25 候选集内部的 SQL WHERE 子句中（硬过滤），不像实体加分那样可以被其他维度补偿。

**根因**：查询端 event_type 提取和索引端 unit_type 存储之间没有词表对齐机制。

**影响面**：所有带事件类型过滤的查询。

---

### 缺陷 3：FTS5 默认分词器无法处理连续中文文本

**位置**：`src/knowledge_base.py` FTS5 建表语句

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_units_fts USING fts5(
    ku_id UNINDEXED, summary, unit_type, source_name,
    evidence_text, entity_mentions, entity_names, tags
)
-- 无 tokenize 参数，默认使用 unicode61
```

**问题**：默认 `unicode61` 分词器不做中文分词。连续中文字符串被当作一个 token。

**各字段影响**：
| 字段 | 存储形式 | 分词效果 |
|------|---------|---------|
| entity_mentions | 空格分隔的实体名 | 正常分词 ✓ |
| entity_names | 空格分隔 | 正常分词 ✓ |
| summary | 连续中文文本 | 整句一个 token ✗ |
| evidence_text | evidence 空格拼接，每条内部可能连续 | 部分受影响 ✗ |
| unit_type | 短词 | 通常正常 ✓ |

**实际效果**：BM25 主要依赖 `entity_mentions` 和 `entity_names` 命中，summary 和 evidence_text 中的语义信息几乎无法被 token 级匹配检索到。

**查询端**：`_tokenize_query()` 提取 `[\u4e00-\u9fff]{2,}` 得到如 "小米集团"，但匹配不到 summary 中的 "小米集团发布了新款SU7电动汽车"（整句一个 token）。

**根因**：FTS5 未配置中文分词器（如 jieba tokenizer 或 simple tokenizer）。

**影响面**：所有依赖 summary / evidence_text 文本匹配的查询。

---

## P1 缺陷

### 缺陷 4：打分校准问题——实体加分压制 BM25 文本信号

**位置**：`src/retrieval/knowledge_search.py` `_score_final_hit()`

**问题**：
1. **实体加分不区分匹配程度**：1 个实体匹配 = 5.0，3 个实体匹配也是 5.0
2. **BM25 分和固定加分不在同一量级**：BM25 最相关 -0.5，最不相关 -8.0，差值 7.5。实体加分固定 5.0，一条不相关但有实体加分的文档可超过高度相关但没有实体加分的文档
3. **BM25 本身是负数**：FTS5 的 `bm25()` 返回负数，直接当正数用导致分值含义混乱

**影响面**：所有 BM25 检索的排序质量。

---

### 缺陷 5：时间解析回退——复杂查询时间提取不可靠

**位置**：`src/intent/classifier.py` `_extract_time_expression()`

```python
def _extract_time_expression(self, parsed, raw_query):
    time_expression = parsed.get("time_expression", "")
    if isinstance(time_expression, str) and time_expression.strip():
        return time_expression.strip()
    return raw_query  # ← 整个原始查询
```

**问题**：LLM 不返回 `time_expression` 时，整句查询被传入 `parse_time_range()`。

**风险场景**：
| 查询 | LLM 返回 time_expression | 实际解析结果 |
|------|------------------------|------------|
| "小米集团过去一年做的事情" | "过去一年" | 正确 ✓ |
| "查看小米集团2023年收购的公司的2024年业绩" | 无 | 整句解析 → 只匹配到 2024 → 丢失 2023 年事件 ✗ |

**根因**：无结构化回退策略。

**影响面**：复杂时间查询。

---

### 缺陷 6：Cluster 无直接检索——聚合视图完全依赖 KU 反查

**位置**：`src/retrieval/knowledge_search.py` `_build_ranked_result()`

**问题**：EventCluster 的检索路径只有两条：
1. 通过选中 KU 的 `cluster_id` 反查
2. 通过 `find_related(primary_entity_ids=...)` 关联查找

没有直接的 cluster 级别搜索。Cluster 自身的 `title` 和 `summary` 完全没有被检索。

**影响**：
- 用户做概念级查询（如"最近的并购事件"）时，只能通过 KU 文本匹配再反查 cluster
- 高质量 EventCluster 如果成员 KU 不在 BM25 top 60 中，cluster 完全不可见

**影响面**：所有需要事件级聚合视图的查询。

---

## P2 缺陷

### 缺陷 7：两条搜索路径打分不一致

**位置**：`_score_final_hit()` vs `_score_in_memory_unit()`

| 维度 | BM25 路径 | 内存路径 |
|------|----------|---------|
| 文本分 | FTS5 bm25() (负数) | 精确匹配 3.0 / token 0.5 |
| 时效 | timestamp / 10^13 | timestamp / 10^9 |

时效加分差 4 个数量级。同一条数据在两个路径下会产生完全不同的排序。

**影响面**：使用 `search_articles()` 的场景。

---

### 缺陷 8：图谱增强只做加法——无法优化初始检索

**位置**：`src/orchestration/graph.py` `run_pipeline()`

**问题**：图谱增强发生在 BM25 检索完成之后。图谱只能增加结果，不能改进初始 BM25 检索质量。

**缺失能力**：
- 初始 BM25 遗漏的关键 KU 无法通过图谱弥补
- 图谱已知关系（A 持股 B）未用来扩展查询词
- GraphRAG 的真正价值在于"用图结构指导检索"

**影响面**：所有启用图谱增强的查询。

---

## 补充缺陷（第二轮挖掘）

### 缺陷 9（P0）：`find_related()` 只查 `primary_entity_id`，非主实体的 Cluster 被遗漏

**位置**：`src/event_merging.py:420-434`

```python
where_clauses.append(f"primary_entity_id IN ({placeholders})")
```

一个 EventCluster 有 `entity_ids = ["A", "B", "C"]` 但 `primary_entity_id = "A"`。当用户查询实体 "B" 时，即使 B 参与了这个 Cluster，`find_related()` 也找不到。

**在检索结果补全阶段**（`knowledge_search.py:202-206`），这意味着 Cluster 补全只能看到主实体匹配的 Cluster，遗漏了大量次实体参与的 Cluster。

**影响面**：所有涉及多实体事件的查询，次实体的 Cluster 补全。

---

### 缺陷 10（P1）：Entity/Cluster 补全存在过度扩展

**位置**：`src/retrieval/knowledge_search.py:191-208`

从所有选中 KU 中收集所有实体的 entity_id，然后用这些 ID 去 `find_related()` 找 Cluster。如果 top 5 KU 提到小米、雷军、美团、王兴，会拉回这 4 个实体的所有 Cluster，包括大量与原始查询无关的结果。

**根因**：补全策略不做意图过滤，"KU 提到的实体"不等价于"查询关心的实体"。

**影响面**：所有返回 EventCluster 的查询。

---

### 缺陷 11（P1）：无结果去重/多样化——同一事件多来源占满 top K

纯相关性排序导致同一 EventCluster 的不同来源报道占满 top K。用户看到 10 条几乎相同的 KU 而非 10 条不同事件的覆盖。

**缺失能力**：MMR（Maximal Marginal Relevance）或 Cluster-aware 多样化策略。

**影响面**：所有热门事件/热门实体的查询。

---

### 缺陷 12（P1）：图谱检索只做 1-hop Entity→Cluster→Entity

**位置**：`src/graph/knowledge_retrieval.py:122-143`

Cypher 查询严格 2-hop，不支持：
- Entity → Entity 直接关系查询（持股、供应、合作）
- 多跳推理：A 参与事件 X → X 涉及 B → B 参与事件 Y → Y 涉及 C
- 时间加权路径发现

对 `EVENT_IMPACT_ANALYSIS` 和 `RELATIONSHIP_QUERY` skill，1-hop 图遍历不够。

**影响面**：关系查询和影响分析类 skill。

---

### 缺陷 13（P2）：`graph/queries.py` 是 legacy 死代码

**位置**：`src/graph/queries.py`

查询基于旧的 `Company` 标签和 `GUARANTEES` 关系，与当前 `Entity + EventCluster + INVOLVED_IN` 模型不匹配。如有代码引用会产生误导性查询结果。

---

### 缺陷 14（P2）：entity_ids 的 LIKE 过滤脆弱且低效

**位置**：`src/knowledge_base.py:615-617`

```python
entity_conditions = [f"{alias}.entity_ids LIKE ?" for _ in entity_ids]
params.extend([f'%"{entity_id}"%' for entity_id in entity_ids])
```

JSON 数组字符串 + LIKE 子串匹配：
- entity_id 互相为子串时误匹配
- 前缀 `%` 阻止索引使用
- JSON 格式变化导致匹配失败

---

## 第三轮挖掘：检索策略与意图感知

### 缺陷 15（P1）：所有意图类型走同一条检索路径——无意图感知的检索策略

**位置**：`src/orchestration/graph.py` `run_pipeline()`

不论用户意图是 `ENTITY_OVERVIEW`、`EVENT_IMPACT_ANALYSIS` 还是 `TOPIC_RESEARCH`，都走完全相同的检索流程。唯一区分发生在结果格式化阶段，而不是检索阶段。

不同意图应有的检索策略：

| 意图 | 应有策略 | 当前行为 |
|------|---------|---------|
| ENTITY_OVERVIEW | 实体优先：高权重拉取该实体所有 KU | 同 BM25 |
| EVENT_IMPACT_ANALYSIS | 事件优先：先找焦点事件，再沿图扩散 | 同 BM25，图扩散在检索后 |
| TOPIC_RESEARCH | 主题优先：按主题关键词/标签搜索 | 同 BM25，无实体时 BM25 效果差 |
| RELATIONSHIP_QUERY | 关系优先：直接查图，BM25 辅助 | 同 BM25，图在后 |

**TOPIC_RESEARCH 的特殊风险**：用户说"半导体行业最近的变化"，LLM 可能不提取实体，`entities=[]`。BM25 搜索虽然能跑，但打分时无实体加分，结果完全依赖 BM25 文本分——而 BM25 对连续中文文本效果很差。

---

### 缺陷 16（P1）：无查询松弛级联——失败时不自动降级

当前检索是单次尝试。健全的检索系统应有松弛级联：

```
尝试 1：精确实体 + 精确 event_type + 精确时间 → 失败
尝试 2：精确实体 + 放宽 event_type + 精确时间 → 失败
尝试 3：精确实体 + 无 event_type + 放宽时间   → 失败
尝试 4：模糊实体匹配 + 纯文本 BM25
```

实体硬门和 event_type 硬过滤的组合意味着：只要其中一个维度不对齐，整个检索就失败。

---

### 缺陷 17（P2）：IntentClassifier 每次 parse 都创建新 LLM 客户端

`run_pipeline()` 每次调用都创建新的 `IntentClassifier` 和 `KnowledgeSearcher`。对于高频调用场景（API 服务），每次请求都有 LLM 客户端初始化和 SQLite 连接重建开销。

---

## 完整优先级排序

| 优先级 | # | 缺陷 | 核心问题 |
|--------|---|------|---------|
| **P0** | 1 | 实体硬门 | 无实体即无结果，无退化搜索 |
| **P0** | 2 | event_type 词表断层 | 查询端和索引端词汇不对齐 |
| **P0** | 3 | FTS5 中文分词 | summary/evidence 连续文本不可检索 |
| **P0** | 9 | find_related 只查主实体 | 次实体的 Cluster 被遗漏 |
| **P1** | 4 | 打分校准 | 实体加分压制 BM25，量纲混乱 |
| **P1** | 5 | 时间解析回退 | 复杂查询时间提取不可靠 |
| **P1** | 6 | Cluster 无直接检索 | 聚合视图依赖 KU 反查 |
| **P1** | 10 | Cluster 补全过度扩展 | 不做意图过滤导致噪声 |
| **P1** | 11 | 无结果多样化 | 同一事件多来源占满 top K |
| **P1** | 12 | 图谱 1-hop | 不支持关系推理和多跳遍历 |
| **P1** | 15 | 无意图感知检索 | 所有意图走同一条 BM25 路径 |
| **P1** | 16 | 无松弛级联 | 失败时不自动降级 |
| **P2** | 7 | 两条路径打分不一致 | 相同数据不同排序 |
| **P2** | 8 | 图谱只做加法 | 无法用图结构优化初始检索 |
| **P2** | 13 | legacy 死代码 | 与当前图模型不匹配 |
| **P2** | 14 | LIKE 过滤 | 脆弱且低效 |
| **P2** | 17 | 每次新建客户端 | 高频场景初始化开销 |

## 分析维度总结

1. **意图解析质量**（缺陷 1, 2, 5, 16）：实体硬门、词表断层、时间解析、无松弛级联
2. **FTS 索引能力**（缺陷 3, 14）：中文分词缺失、BM25 退化为实体匹配器、LIKE 脆弱
3. **检索策略**（缺陷 15, 16）：无意图感知、无松弛级联
4. **结果后处理**（缺陷 9, 10, 11, 4）：Cluster 补全只查主实体、过度扩展、无多样化、打分校准
5. **图谱集成**（缺陷 12, 8, 13）：1-hop 限制、只做加法、legacy 死代码
6. **代码质量**（缺陷 7, 17）：打分不一致、客户端重建

## 分析状态

- [x] P0 缺陷识别（4 个）
- [x] P1 缺陷识别（8 个）
- [x] P2 缺陷识别（5 个）
- [x] 分析完成
- [ ] 修复方案设计（后续）
