# User Testing Findings

> Append-only 文件。不要编辑或删除已有发现。
> 每个 finding 是一个 H2 section，ID 格式：`F<YYYYMMDD>-<session-sequence>`
> Status 值：OPEN, CONFIRMED, FIXED, WONTFIX, DUPLICATE
> Severity 值：CRITICAL, HIGH, MEDIUM, LOW

---

<!-- 在此行下方追加新发现 -->

## F20260509-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S001 |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #10 |

### Summary
搜索"小米集团"返回 141 个 event_clusters，但大量与小米集团完全无关（如京东具身大模型、西班牙首相访华等）。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团"
```
返回 `event_clusters` 数量为 141，但前 5 个 cluster 中有 3 个与小米无关：
- "京东发布具身大模型JoyAI-RA"
- "西班牙首相桑切斯表示合作不会削弱科学"
- "京东计划在100个城市开设国民好车交付中心"

### Expected Behavior
event_clusters 应主要包含与小米集团相关的聚类事件。无关 cluster 不应出现。

### Impact
作为分析师，我需要快速扫描小米集团的事件聚类。大量无关 cluster 严重干扰信息获取效率。这与 Defect #10（Cluster 补全过度扩展）吻合——系统从 KU 中提取的所有实体（包括阿里巴巴、美团、京东等）去查找 cluster，导致噪声结果。

---

## F20260509-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S001 |
| **Severity** | LOW |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
实体类型分类有误——"市场份额"被标注为 Person，"股价"被标注为 Product。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团"
```
entities 列表中包含：
- `ent_5528d9debe35`: canonical_name="市场份额", entity_type="Person"
- `ent_7102aae8032e`: canonical_name="股价", entity_type="Product"

### Expected Behavior
"市场份额"应为 Concept 或 Metric 类型，"股价"应为 Concept 或 Indicator 类型。不应为 Person 或 Product。

### Impact
低。不影响检索正确性，但会影响下游对实体类型的信任度。如果 agent 系统依赖 entity_type 做路由决策，可能导致错误。

---

## F20260509-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S001 |
| **Severity** | MEDIUM |
| **Category** | error-handling |
| **Status** | FIXED |
| **Related Defect** | - |

### Summary
Neo4j 图数据库未运行时，系统默认 `graph_enabled: True` 但 `graph_used: False`，errors 中包含原始连接异常堆栈。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团"
```
返回结果中：
- `graph.graph_enabled`: true（默认启用图谱）
- `graph.graph_used`: false（实际未使用）
- `errors`: 包含完整 Neo4j 连接拒绝的异常堆栈信息

### Expected Behavior
当 Neo4j 不可用时，理想行为：
1. 自动检测 Neo4j 状态并设置 `graph_enabled: false`，或
2. errors 中提供简洁的用户友好提示（如"图谱服务不可用，已降级为纯文本检索"），而非原始异常堆栈。

### Impact
作为分析师看到原始异常堆栈会感到困惑——是系统出错了还是只是部分功能不可用？JSON errors 字段应包含结构化错误信息，而非 Python traceback。

---

## F20260509-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S002 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3, #1 |

### Summary
ENTITY_TIMELINE 查询指定近一年时间范围(2025-04-01 到 2026-04-13)，但仅返回 7 条结果且集中在最近半个月(3 个日期)，2025-04-01 到 2026-03-30 之间完全空白。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --intent ENTITY_TIMELINE --time-range 2025-04-01:2026-04-13
```
返回 total_count=7，实际日期分布：
- 2026-03-31: 1 条（小米Q1出货量）
- 2026-04-09: 3 条（冰淇淋发布、股价下跌、内存涨价）
- 2026-04-13: 2 条（首相访问、雷军演讲）
- N/A: 1 条（event_time 为 None）

### Expected Behavior
作为分析师查询"小米集团过去一年的事件时间线"，期望看到全年各季度的事件分布，即使某些时段事件较少也不应出现近一年的空白。至少应覆盖 2025-Q2 到 2026-Q1 的主要事件。

### Impact
严重。分析师依赖时间线做事件梳理和报告撰写。近一年的空白意味着系统要么数据覆盖不足，要么时间过滤有 bug。结合 Defect #3（FTS5 中文分词问题），可能大量 2025 年的 KU 因 summary 无法被 token 匹配而遗漏。

---

## F20260509-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S002 |
| **Severity** | LOW |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
部分 KU 的 event_time 为 None，在时间线查询中无法定位时间点。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --intent ENTITY_TIMELINE --time-range 2025-04-01:2026-04-13
```
返回 7 条 KU 中有 1 条 event_time 为 None：
- ku_6f4137707b1be274: "百度、腾讯、小米飘绿"
  - event_time: None
  - published_at: 2026-04-10T12:10:11Z

### Expected Behavior
当 event_time 为 None 但 published_at 可用时，应回退使用 published_at 作为时间参考，或在输出中标注"时间未解析"。

### Impact
低。时间线中会出现无法定位时间的事件，但不影响整体检索功能。

---

## F20260509-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S003 |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #12 |

### Summary
RELATIONSHIP_QUERY 意图完全依赖图谱，但 Neo4j 未运行时系统不发出警告，静默降级为普通 BM25 搜索，返回与关系查询无关的结果。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --intent RELATIONSHIP_QUERY --target-entity "腾讯控股" --hops 2
```
返回结果：
- `graph_data.nodes`: 0（空）
- `graph_data.edges`: 0（空）
- `graph.graph_used`: false
- `knowledge_units`: 12 条（与 S001 普通搜索结果完全相同的 BM25 结果）
- `total_count`: 12

分析师期望看到小米集团与腾讯控股之间的关系路径（如共同投资、供应链关系、竞合关系等），但实际得到的是普通的文本搜索结果。

### Expected Behavior
当 RELATIONSHIP_QUERY 的图谱不可用时：
1. 明确提示用户"关系查询需要图谱服务，当前不可用"
2. 不应静默降级为普通搜索——这会误导分析师以为返回结果就是关系分析
3. 考虑基于 BM25 的共现关系作为降级方案（两个实体同时出现在同一 KU 中）

### Impact
CRITICAL。分析师发起关系查询时期望得到结构化的关系数据。静默返回无关的文本搜索结果会导致严重的决策误导。这与 Defect #12（图谱 1-hop 限制）和 Defect #15（无意图感知检索）相关——即使图谱可用，关系查询也只是普通 BM25 + 后置图谱增强。

---

## F20260509-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S005 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #2 |

### Summary
event_type 硬过滤导致中文"债务违约"和英文"debt_default"都返回 0 结果，完美验证了 Defect #2（词表断层）。

### Reproduction
```
# Step 1: 无过滤
uv run knowledge-cli search --entities "恒大集团" --intent ENTITY_OVERVIEW
# → total_count: 1, unit_type: "financial_statement"

# Step 2: 中文过滤
uv run knowledge-cli search --entities "恒大集团" --event-types "债务违约"
# → total_count: 0

# Step 3: 英文过滤
uv run knowledge-cli search --entities "恒大集团" --event-types "debt_default"
# → total_count: 0
```

唯一的恒大相关 KU 类型为 "financial_statement"（世联行应收恒大款项），与用户输入的 "债务违约" 不匹配。SQL `WHERE unit_type IN ('债务违约')` 直接排除。

### Expected Behavior
1. event_type 过滤应有模糊匹配或词表映射（"债务违约" → "financial_statement"/"debt_default"/"debt_breach" 等）
2. 至少应返回与恒大债务相关的所有 KU，不论 unit_type 标注为何种词汇
3. 英文 "debt_default" 应映射到中文词表中的对应条目

### Impact
HIGH。分析师搜索"恒大集团 债务违约"期望得到恒大债务危机的全面事件记录。0 结果意味着这个核心查询完全失败。更严重的是，恒大作为近年来最重要的债务违约事件之一，整个知识库仅包含 1 条相关 KU，说明数据覆盖也存在严重不足。

---

## F20260509-008

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S005 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #1, #16 |

### Summary
搜索"恒大集团"仅返回 1 条 KU（世联行应收款项），恒大本身的核心事件（债务违约、清盘、重组等）完全缺失。

### Reproduction
```
uv run knowledge-cli search --entities "恒大集团" --intent ENTITY_OVERVIEW
# → total_count: 1
# → 唯一 KU: "截至2025年末，世联行应收恒大集团及其关联方应收款项总额为11.45亿元"
# → unit_type: financial_statement
```

### Expected Behavior
恒大集团是中国房地产危机的核心企业，应有大量相关 KU 覆盖：
- 债务违约事件
- 清盘程序
- 重组进展
- 关联影响（供应商、购房者、金融机构）

### Impact
HIGH。数据覆盖不足直接影响分析师对重大风险事件的追踪能力。也可能与 Defect #1（实体硬门）和 Defect #16（无松弛级联）有关——如果恒大的某些 KU 中实体名不是精确匹配"恒大集团"（如"中国恒大"、"恒大地产"等），则会被完全过滤掉。

---

## F20260509-009

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-101500 |
| **Persona** | analyst |
| **Scenario** | S005 |
| **Severity** | MEDIUM |
| **Category** | output-quality |
| **Status** | FIXED |
| **Related Defect** | - |

### Summary
Neo4j 的 WARNING 级别通知（property key does not exist: primary_entity_id）输出到 stdout，与 JSON 结果混合，导致 JSON 解析失败。

### Reproduction
```
uv run knowledge-cli search --entities "恒大集团" --intent ENTITY_OVERVIEW
```
stdout 输出以 Neo4j 警告开头：
```
Received notification from DBMS server: <GqlStatusObject gql_status='01N52', status_description='warn: property key does not exist. The property `primary_entity_id` does not exist in database `neo4j`...
```
这个警告出现在 JSON 对象之前，导致整个 stdout 不是合法 JSON。

### Expected Behavior
1. Neo4j 的 WARNING 应输出到 stderr，不污染 stdout 的 JSON 输出
2. 或者 CLI 应捕获这些警告并放入 errors 字段
3. stdout 应只包含纯净的 JSON 结果

### Impact
MEDIUM。任何将 knowledge-cli 集成到程序化系统中的开发者都会遇到 JSON 解析失败。必须使用 `2>/dev/null` 或手动过滤才能获得合法 JSON。这与 Defect #13（legacy 死代码引用不存在的属性）相关——`primary_entity_id` 属性在 Neo4j 中不存在，说明代码与图模型不同步。

---

## F20260509-010

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-developer-20260509-154500 |
| **Persona** | developer |
| **Scenario** | ad-hoc (新能源探索) |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #15 |

### Summary
COMPARATIVE_ANALYSIS 意图查询"宁德时代"和"比亚迪"时，返回的 20 条 KU 全部只涉及宁德时代，比亚迪完全不出现在任何 KU 中。对比分析退化为单实体搜索。

### Reproduction
```
uv run knowledge-cli search --entities "宁德时代" "比亚迪" --intent COMPARATIVE_ANALYSIS
```
- 宁德时代 mentioned in KUs: 20/20
- 比亚迪 mentioned in KUs: 0/20
- entities 列表中包含 128 个实体，但返回的 KU 没有覆盖两个查询实体

### Expected Behavior
COMPARATIVE_ANALYSIS 应返回同时涉及两个实体的 KU，或至少各实体的代表性 KU 交替出现。20 条结果中 0 条提及比亚迪是完全不可接受的。

### Impact
CRITICAL。对比分析是分析师核心需求之一。当用户明确要求比较 A 和 B 时，系统只返回 A 的信息，完全失去"对比"意义。这与 Defect #15（无意图感知检索）直接相关——COMPARATIVE_ANALYSIS 意图没有专门的检索策略，只是普通 BM25 搜索。宁德时代 KU 更多（total_count=53 vs 15），BM25 分数碾压比亚迪。

---

## F20260509-011

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-developer-20260509-154500 |
| **Persona** | developer |
| **Scenario** | ad-hoc (新能源探索) |
| **Severity** | HIGH |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | #2 |

### Summary
unit_type 字段中英文严重混用，73 个唯一值中 38 个中文、35 个英文，同一概念用不同语言标注。

### Reproduction
跨 6 组新能源搜索，unit_type 示例：
- 中文：薪酬增长、合作内容、商务合作、发布会、股权投资、假消息传播
- 英文：stock_price_change、financial_performance、fire_incident、company_announcement
- 语义重复：中文"股价上涨" vs 英文"stock_price_change" vs 英文"price_movement" vs 中文"价格上涨"

### Expected Behavior
unit_type 应使用统一的词表（全中文或全英文），并通过标准化映射确保语义一致性。

### Impact
HIGH。这与 Defect #2（词表断层）同根——LLM 抽取时自由选择中英文，导致下游过滤、聚合、统计全部失效。用户按 event_type 过滤时必须猜测系统用的是哪种语言。

---

## F20260509-012

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-developer-20260509-154500 |
| **Persona** | developer |
| **Scenario** | ad-hoc (新能源探索) |
| **Severity** | MEDIUM |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
event_time 大量缺失，跨 6 组搜索共 103 条 KU 中有 56 条（54%）event_time 为 None。

### Reproduction
各组搜索的 event_time 缺失率：
| 搜索 | 有时间 | 无时间 | 缺失率 |
|------|--------|--------|--------|
| 比亚迪 OVERVIEW | 6 | 9 | 60% |
| 宁德时代 OVERVIEW | 10 | 10 | 50% |
| 新能源汽车 TOPIC | 8 | 12 | 60% |
| 光伏 TOPIC | 6 | 8 | 57% |
| 比亚迪 TIMELINE | 5 | 9 | 64% |
| 宁德时代vs比亚迪 | 12 | 8 | 40% |

### Expected Behavior
超过一半的 KU 缺少 event_time 是严重的数据质量问题。published_at 在大多数情况下可用，应作为回退时间源。

### Impact
MEDIUM。时间线查询（ENTITY_TIMELINE）尤其受影响——缺失时间的 KU 无法被定位在时间轴上，导致时间线出现虚假空白。

---

## F20260509-013

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-developer-20260509-154500 |
| **Persona** | developer |
| **Scenario** | ad-hoc (新能源探索) |
| **Severity** | LOW |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #10 |

### Summary
宁德时代搜索返回 96 个 event_clusters，远超 KU 数量（20），大量 cluster 与宁德时代无直接关联。

### Reproduction
```
uv run knowledge-cli search --entities "宁德时代" --intent ENTITY_OVERVIEW
```
- total_count: 53, 返回 KU: 20
- event_clusters: 96（cluster 数量是 KU 的近 5 倍）
- 对比搜索返回 entities: 101

### Expected Behavior
cluster 补全应限制在与查询实体直接相关的范围内。96 个 cluster 中大量是通过 Defect #10（过度扩展）从 KU 中提及的次要实体拉取的无关 cluster。

### Impact
LOW。cluster 过度扩展问题在上一轮已记录（F20260509-001），此处确认宁德时代也存在同样问题，且比例更高（96 clusters / 20 KUs vs 小米的 141/12）。
