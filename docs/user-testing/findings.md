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
| **Status** | IMPROVED |
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
| **Status** | FIXED |
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

---

## F20260509-014

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S004 |
| **Severity** | MEDIUM |
| **Category** | ux |
| **Status** | FIXED |
| **Related Defect** | #1, #16 |

### Summary
搜索不存在的实体时返回空结果且 errors 为空，AI 应用无法区分"实体未找到"和"系统错误"。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "完全不存在的公司名称XYZ" 2>/dev/null
```
返回结果：
- total_count: 0
- knowledge_units: []
- errors: []
- matched_entity_ids: []
- bm25_count: 0

### Expected Behavior
errors 字段应包含提示性信息，如 `{"code": "ENTITY_NOT_FOUND", "message": "未找到实体'完全不存在的公司名称XYZ'"}`。对于 AI 应用集成，需要结构化的错误码以便下游 LLM 生成用户友好的回复。

### Impact
MEDIUM。AI 应用集成时，下游 LLM 收到空结果和空 errors，无法判断是数据缺失还是系统故障。应提供至少一个 warning 级别的提示。

---

## F20260509-015

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S006 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #1, #16 |

### Summary
英文实体别名 "BYD" 搜索返回 0 结果，而中文 "比亚迪" 返回 16 条。中文简称（小米、腾讯）可以正确解析，但跨语言别名完全失败。

### Reproduction
```
# 中文全名 → 16 results
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "比亚迪" --intent ENTITY_OVERVIEW
# → total_count: 16, matched_entity_ids: ['ent_...']

# 英文别名 → 0 results
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "BYD" --intent ENTITY_OVERVIEW
# → total_count: 0, matched_entity_ids: [], bm25_count: 0

# 对比：中文简称正常工作
# "小米" → total_count: 15 (与"小米集团"完全一致)
# "腾讯" → total_count: 23 (与"腾讯控股"完全一致)
```

### Expected Behavior
"BYD" 应解析到与 "比亚迪" 相同的实体。系统应有跨语言别名映射机制，或至少在实体硬门失败后降级为 BM25 文本搜索（summary/evidence 中可能包含 "BYD"）。

### Impact
HIGH。国际化的 AI 应用用户可能使用英文名称查询中国公司。当前行为（0 结果 + 无提示）比返回不精确的结果更差。确认了 Defect #1（实体硬门）和 Defect #16（无松弛级联）——实体未匹配时 BM25 完全不执行。

---

## F20260509-016

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S013 |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | PARTIAL |
| **Related Defect** | #1, #3, #15 |

### Summary
话题搜索能否返回结果完全取决于该话题词是否在摄取时被提取为实体，用户和 AI 应用无法预知哪些话题能搜到。"半导体"(19条)、"AI芯片"(5条)、"大模型"(16条) 有结果，但 "量化交易" 和 "供应链金融" 返回 0 条。

### Reproduction
```
# 话题存在于实体库 → 有结果
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "半导体" --intent TOPIC_RESEARCH
# → total_count: 19, matched_entity_ids: ['ent_f0506f42d994']

PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "大模型" --intent TOPIC_RESEARCH
# → total_count: 16, matched_entity_ids: ['ent_c9e4494a03c1']

# 话题不在实体库 → 0 结果
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "量化交易" --intent TOPIC_RESEARCH
# → total_count: 0, matched_entity_ids: [], bm25_count: 0

PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "供应链金融" --intent TOPIC_RESEARCH
# → total_count: 0, matched_entity_ids: [], bm25_count: 0
```

### Expected Behavior
对于话题研究类查询（TOPIC_RESEARCH），当实体解析失败时，应自动降级为 BM25 全文搜索。即使 FTS5 中文分词效果有限（Defect #3），也应该尝试在 entity_mentions 和 unit_type 字段中匹配。完全跳过 BM25 是不可接受的。

### Impact
CRITICAL。这是 AI 应用集成的核心障碍。AI 应用的用户会问各种话题（行业趋势、政策变化、技术方向），不可能每个话题都在实体库中有对应条目。当前系统只能搜索"已知的实体"，不能做真正的知识检索。这与 Defect #1（实体硬门）、Defect #3（FTS5 中文分词）和 Defect #15（无意图感知检索）三重叠加导致。

---

## F20260509-017

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S013 |
| **Severity** | MEDIUM |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
行业/话题词被错误分类为实体类型。半导体被标注为 "Person"，稀土和军工被标注为 "Product"，在手订单被标注为 "Person"。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "半导体" --intent TOPIC_RESEARCH
```
返回的 KU 中实体类型：
- `ent_f0506f42d994`: canonical_name="半导体", entity_type="Person"
- `ent_a9ba1e0a9849`: canonical_name="稀土", entity_type="Product"
- `ent_c1da74e5c73f`: canonical_name="军工", entity_type="Product"
- `ent_b86e10e3c6ae`: canonical_name="在手订单", entity_type="Person"

### Expected Behavior
半导体应为 Industry/Sector/Concept，稀土应为 Commodity/Industry，军工应为 Industry，在手订单应为 Metric/Concept。这些错误分类会影响 AI 应用依赖 entity_type 做路由或过滤决策。

### Impact
MEDIUM。与 F20260509-002（"市场份额"标注为 Person）同根问题。实体类型分类由 LLM 在摄取时自由决定，缺乏受控词表约束。AI 应用如果依赖 entity_type 做逻辑分支，会产生错误行为。

---

## F20260509-018

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S013 |
| **Severity** | LOW |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #11 |

### Summary
"大模型"话题搜索返回 16 条 KU，其中第 3 条和第 4 条是同一事件的近重复报道（高盛/摩根士丹利测试 Anthropic Mythos 大模型）。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "大模型" --intent TOPIC_RESEARCH
```
KU 3: "高盛、摩根士丹利等银行正在测试Anthropic的Mythos大模型..."
KU 4: "高盛、摩根士丹利等华尔街银行正在测试Anthropic的Mythos大模型..."

### Expected Behavior
同一事件的不同来源报道应被去重或合并，不应在 top-K 中占多个位置。理想情况下应保留信息量最大的版本。

### Impact
LOW。确认了 Defect #11（无去重）。对于 AI 应用，重复信息浪费 context window 但不致命。

---

## F20260509-019

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-170000 |
| **Persona** | analyst |
| **Scenario** | S014 |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #12 |

### Summary
EVENT_IMPACT_ANALYSIS 图谱增强只提供 Entity→INVOLVED_IN→EventCluster 单一关系类型，无法展示因果链或影响传导路径。边类型 100% 为 INVOLVED_IN，无投资/供应/竞争等直接实体关系。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "小米集团" --intent EVENT_IMPACT_ANALYSIS
```
- graph_nodes: 37, graph_edges: 40
- 所有 40 条边的 type 均为 "INVOLVED_IN"
- 无 Entity→Entity 直接关系边
- 无 EventCluster→EventCluster 因果/时序边

恒大集团搜索也验证了同样问题：
- graph_nodes: 9, graph_edges: 8
- 100% INVOLVED_IN

### Expected Behavior
影响分析至少需要：
1. Entity→Entity 关系边（持股、供应、合作、竞争）
2. 时序排序（先发生的事件→后发生的事件）
3. 影响强度标注

### Impact
MEDIUM。图谱增强能发现 BM25 漏掉的关联 cluster（如恒大开庭审理），但关系类型单一，无法支持真正的影响链分析。确认了 Defect #12（图谱 1-hop 限制）。

---

## F20260509-020

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #1 (FIXED), #3, #4 |

### Summary
Defect #1（实体硬门）已在代码层面修复——BM25 现在始终执行。但 COMPARATIVE_ANALYSIS 意图下多实体查询仍返回 0 结果：BM25 找到 20 个候选，但打分阈值将全部过滤掉。相同实体用 ENTITY_OVERVIEW 查询可返回 4 条高相关结果。已修复：改为 union+coverage_bonus 策略，不再依赖交集。

### Reproduction
```
# COMPARATIVE_ANALYSIS → 0 results despite BM25 finding candidates
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" "以色列" --intent COMPARATIVE_ANALYSIS
# → total_count: 0, bm25_count: 20, matched_entity_ids: []

# ENTITY_OVERVIEW → 4 relevant results, same entities
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" "以色列" --intent ENTITY_OVERVIEW
# → total_count: 4, bm25_count: 60, matched_entity_ids: []
# KU 1: 内塔尼亚胡宣布以军加大对伊朗境内目标打击强度
# KU 2: 内塔尼亚胡与特朗普通话，要求美方不要同意与伊朗停火
# KU 3: 以色列国防军称美国与伊朗停火安排不包括黎巴嫩
# KU 4: 以色列官员对美伊临时停火协议表示担忧
```

同时验证 Defect #1 修复：
- "伊朗": matched_entity_ids=[], bm25_count=60, total_count=5 → BM25 正常执行
- "霍尔木兹海峡": matched_entity_ids=[], bm25_count=60, total_count=4 → BM25 正常执行
- "量化交易": matched_entity_ids=[], bm25_count=0, total_count=0 → BM25 执行但 FTS 无匹配（Defect #3）

### Expected Behavior
1. COMPARATIVE_ANALYSIS 不应比 ENTITY_OVERVIEW 返回更少的结果——至少应返回相同结果
2. 当 BM25 找到候选但打分过滤后为空时，应降低阈值或返回 top BM25 结果而非 0
3. 不同 intent 不应导致如此巨大的结果差异（0 vs 4）

### Impact
CRITICAL。COMPARATIVE_ANALYSIS 是 AI 应用的核心使用场景之一。当用户要求"比较伊朗和以色列"时返回 0 结果，而简单的实体概览反而返回 4 条高相关结果，这对 AI 应用的可信度是严重打击。与 Defect #4（打分校准）相关——无实体加分时，BM25 负分可能全部低于阈值。

---

## F20260509-021

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #15 |

### Summary
RISK_ASSESSMENT 意图对"伊朗"返回的结果与 ENTITY_OVERVIEW 完全一致（相同的 5 条 KU、相同排序），无任何风险相关的额外分析或过滤。不同意图类型走完全相同的检索路径。

### Reproduction
```
# RISK_ASSESSMENT
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" --intent RISK_ASSESSMENT
# → total_count: 5, 相同的 5 条军事 KU

# ENTITY_OVERVIEW
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" --intent ENTITY_OVERVIEW
# → total_count: 5, 完全相同的 5 条 KU
```

### Expected Behavior
RISK_ASSESSMENT 应优先返回风险相关内容（制裁、违约、军事冲突升级等），而非与 ENTITY_OVERVIEW 完全相同的结果。至少应调整排序使风险相关内容排在前面。

### Impact
HIGH。确认了 Defect #15（无意图感知检索）。AI 应用如果依赖不同 intent 获取不同维度的信息，当前系统无法提供这种区分。所有 intent 产出的结果完全相同。

---

## F20260509-022

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #2 |

### Summary
事件类型过滤"军事部署"找到了 4 条 KU，但其中 2 条与伊朗完全无关（法国戴高乐航母部署、黎巴嫩军队部署），说明 event_type 过滤缺乏实体约束。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" --event-types "军事部署"
# → total_count: 4, matched_entity_ids: []

KU 1: 法国'戴高乐'号航母离开希腊苏达湾基地 ← 与伊朗无关
KU 2: 黎巴嫩总理要求黎军队和安全部队加强在贝鲁特的部署 ← 与伊朗无关
KU 3: 伊朗伊斯兰革命卫队航空航天部队部署导弹发射装置 ← 相关
KU 4: 伊朗情报部门周密部署伏击行动 ← 相关
```

### Expected Behavior
event_type 过滤应与实体约束联合生效。当用户搜索"伊朗+军事部署"时，结果应同时满足两个条件：提及伊朗 AND 类型为军事部署。当前行为是只按 event_type 过滤，忽略实体约束（因为 matched_entity_ids 为空）。

### Impact
MEDIUM。当实体未匹配到 entity_id 时，event_type 过滤独立于实体约束运行，返回不相关的结果。AI 应用会将这些不相关结果当作"伊朗军事部署"信息呈现给用户。

---

## F20260509-023

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3 |

### Summary
伊朗相关话题覆盖极度不均衡。"中东战争"返回 11 条、"中东局势"返回 31 条，但"伊朗核协议"、"伊朗制裁"返回 0 条。伊朗自身的 5 条 KU 全部是军事片段，缺少石油、制裁、核协议、外交等关键维度。问题根因是 FTS5 中文分词（Defect #3）：复合词如"伊朗核协议"无法被 BM25 匹配。

### Reproduction
```
# 有结果（作为实体存在于库中）
"中东战争" → 11 KUs (entity: ent_b9fae84de941)
"中东局势" → 31 KUs (entity: ent_1ba13fa117da)

# 有结果（出现在 entity_mentions 中）
"伊朗" → 5 KUs (BM25 匹配)
"霍尔木兹海峡" → 4 KUs (BM25 匹配)
"以色列" → 4 KUs (BM25 匹配)

# 无结果（不在任何 FTS 索引字段中）
"伊朗核协议" → 0 KUs (bm25_count: 0)
"伊朗制裁" → 0 KUs (bm25_count: 0)
"伊朗石油" → 0 KUs (bm25_count: 1, total: 0)
```

### Expected Behavior
"伊朗核协议"和"伊朗制裁"是伊朗相关的核心话题，至少应返回与伊朗核问题或制裁相关的 KU。BM25 应能在 summary 或 evidence_text 中匹配到这些关键词。FTS5 中文分词缺失导致连续中文文本不可检索（Defect #3）。

### Impact
HIGH。对于地缘政治分析类 AI 应用，无法检索"伊朗核协议"或"伊朗制裁"是严重的功能缺失。知识库可能包含相关内容，但 FTS5 分词器无法从连续中文文本中提取匹配。

---

## F20260509-024

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | LOW |
| **Category** | data-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
伊朗相关 5 条 KU 的 event_time 全部为 None（100% 缺失），内容全部是极简短的军事片段（每条 10-20 字），缺乏上下文和详细描述。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" --intent ENTITY_OVERVIEW
```
所有 5 条 KU：
- KU 1: "伊朗情报部门周密部署伏击行动" (15字, event_time: None)
- KU 2: "伊朗方面不急于求成" (9字, event_time: None)
- KU 3: "伊朗军民协同作战执行伏击任务" (14字, event_time: None)
- KU 4: "美国与伊朗同意停火两周" (12字, event_time: None)
- KU 5: "伊朗武装力量保持高度戒备状态" (14字, event_time: None)

### Expected Behavior
KU 应包含足够的上下文信息（时间、地点、参与方、具体事件），而非极简短的片段。event_time 应从 published_at 回退填充。

### Impact
LOW。数据粒度问题——这些 KU 更像新闻标题而非知识单元。对于 AI 应用，缺乏上下文的片段很难被有效利用。

---

## F20260509-025

| Field | Value |
|-------|-------|
| **Date** | 2026-05-09 |
| **Session** | ut-analyst-20260509-173000 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (Iran exploration) |
| **Severity** | LOW |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #10 |

### Summary
伊朗 EVENT_IMPACT_ANALYSIS 返回 51 个 event_clusters，但仅有 5 条 KU，cluster/KU 比例为 10.2:1，远超正常范围。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "伊朗" --intent EVENT_IMPACT_ANALYSIS
# → total_count: 5 KUs, 51 event_clusters
# → cluster_count / ku_count = 10.2
```

对比其他实体：
- 小米: 17 clusters / 15 KUs = 1.1
- 恒大: 2 clusters / 1 KU = 2.0
- 伊朗: 51 clusters / 5 KUs = 10.2

### Expected Behavior
Cluster 补全应与查询实体直接相关。51 个 cluster 中大量来自 KU 提及的次要实体（如"情报部门"、"军民"），通过 Defect #10（过度扩展）拉取。

### Impact
LOW。确认了 Defect #10。大量无关 cluster 会干扰 AI 应用对事件的全局理解。

---

## F20260510-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3 |

### Summary
搜索"海思"（华为芯片子公司 HiSilicon）返回 20 条 KU，其中 0 条与华为海思相关。全部为 BM25 短词碰撞导致的噪声结果：海思科（药企）、蓝思科技、海信家电、海昌智能等。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "海思" --intent ENTITY_OVERVIEW
```
- total_count: 54, ku_count: 20, clusters: 222 (cluster/KU=11.1:1)
- 华为海思相关 KU: 0/20
- 海思科(药企) KU: 1/20
- 完全无关 KU: 19/20
- Top 3: "蓝思科技H股跌超19%", "海思科创新药HSK47388片", "广州慧仑智行科技"

### Expected Behavior
"海思"应解析到华为海思半导体，至少返回与华为芯片相关的 KU。当前 BM25 将"海"和"思"两个字符作为独立 token 匹配到海思科、蓝思科技、海信等完全不相关的公司。

### Impact
CRITICAL。作为芯片行业核心搜索词，"海思"完全无法检索到正确结果。名称碰撞问题对所有 2-3 字短实体名均构成风险。与 Defect #3（FTS5 中文分词）直接相关——短中文字符串被 token 化后匹配范围过宽。

---

## F20260510-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | S007 |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #5 |

### Summary
时间范围过滤完全未生效。4 组不同时间范围（窄/宽/零长度/反向）对"英伟达"搜索返回几乎完全相同的结果（total 52-64, ku 20）。time_range 在 query 和 applied_filters 中正确记录，但实际检索完全忽略。

### Reproduction
```
# 窄范围
uv run knowledge-cli search --entities "英伟达" --time-range "2026-01-01:2026-01-31"
# → total=52, ku=20, dates in result: 2026-04-15~2026-05-09

# 宽范围
uv run knowledge-cli search --entities "英伟达" --time-range "2025-01-01:2026-04-13"
# → total=64, ku=20, dates in result: 2026-04-15~2026-05-09

# 零长度
uv run knowledge-cli search --entities "英伟达" --time-range "2026-01-01:2026-01-01"
# → total=52, ku=20, 无崩溃

# 反向范围
uv run knowledge-cli search --entities "英伟达" --time-range "2026-04-13:2025-01-01"
# → total=52, ku=20, 无错误
```

所有查询的 applied_filters 均正确包含 time_range，但结果完全一致。

### Expected Behavior
1. 窄范围(2026-01)结果应是宽范围(2025-01~2026-04)的子集
2. 零长度范围应返回 0 结果或仅该日期的结果
3. 反向范围应报错或返回空
4. 所有结果日期应在请求的时间范围内

### Impact
CRITICAL。时间范围是分析师和商务用户的核心过滤需求。用户指定"2026年1月"搜索英伟达，实际返回 4-5 月的结果——完全违背用户意图。时间范围参数是"纸面功能"，解析但不执行。与 Defect #5（时间解析回退）相关——时间解析可能成功但过滤逻辑未实现。

---

## F20260510-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3 |

### Summary
搜索"辉达"（NVIDIA 台湾名称）返回 20 条 KU，前 2 条为完全不相关的噪声（"民士达"、"信达生物"）。与"海思"搜索问题同根——BM25 短 token 匹配导致名称碰撞。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "辉达" --intent ENTITY_OVERVIEW
# → total=48, ku=20, bm25=60
# KU1: "民士达一季度实现归母净利润3057.98万元" ← 无关
# KU2: "信达生物涨超4%" ← 无关（"达"字匹配）
# KU3: "英伟达与康宁达成投资协议，承诺投资32亿美元" ← 相关（含"辉达"别名或"英伟达"）
```

### Expected Behavior
"辉达"应解析到英伟达/NVIDIA 实体（辉达是 NVIDIA 的台湾/繁体中文注册名）。当前无法正确解析跨地区别名。

### Impact
HIGH。使用 NVIDIA 台湾名搜索的用户会看到大量噪声。确认了 BM25 短 token 碰撞问题不仅限于"海思"，对所有 2 字短实体名均有影响。

---

## F20260510-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #15 |

### Summary
华为+中芯国际 COMPARATIVE_ANALYSIS 返回 20 条 KU，其中华为 17 条、中芯国际仅 1 条，严重偏向高数据量实体。0 条 KU 同时提及两个实体。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "华为" "中芯国际" --intent COMPARATIVE_ANALYSIS
# → total=64, ku=20
# 华为 coverage: 17/20 (85%)
# 中芯国际 coverage: 1/20 (5%)
# Both entities in same KU: 0/20 (0%)
# Top 3: "问界M6发布", "华为Pura X Max 11999元", "华为Pura X Max 10999元"
```

### Expected Behavior
COMPARATIVE_ANALYSIS 应确保两个实体均衡覆盖（至少各占 30%+），优先返回同时提及两个实体的 KU。当前华为总数据量(84)远超中芯国际(60)，BM25 分数碾压导致中芯国际几乎不可见。

### Impact
HIGH。芯片行业对比分析是核心场景——"华为 vs 中芯国际"代表国内芯片两大力量。17:1 的偏差使对比分析失去意义。虽然英伟达 vs 台积电已改善(12:8)，但数据量差距大的实体对仍严重失衡。

---

## F20260510-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3 |

### Summary
芯片行业核心话题词"芯片制裁"、"光刻"、"芯片国产替代"全部返回 0 结果。而单字/短词"芯片"(49条)、"AI芯片"(5条)、"GPU"(7条)可正常返回。

### Reproduction
```
# 有结果
"芯片" → total=49 (entity in KB)
"AI芯片" → total=5 (entity in KB)
"GPU" → total=7 (entity in KB)
"半导体设备" → total=4 (entity in KB)

# 无结果（bm25_count=0，BM25 也无法匹配）
"芯片制裁" → total=0
"光刻" → total=0
"芯片国产替代" → total=0
```

### Expected Behavior
"芯片制裁"和"光刻"是芯片行业核心话题，即使不作为实体存在，BM25 也应在 summary/evidence 中匹配到相关文本。当前 bm25_count=0 说明 FTS5 索引中完全无法匹配这些复合中文短语。

### Impact
MEDIUM。再次验证 Defect #3（FTS5 中文分词）。芯片行业用户搜索"芯片制裁"或"芯片国产替代"是高频需求，0 结果严重影响使用体验。单字/短词作为实体入库后可检索，但组合短语完全不可检索。

---

## F20260510-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | MEDIUM |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
芯片行业搜索中实体类型分类错误持续出现且模式扩大："台南"=Person、"一季度"=Person、"销售额"=Person、"数据中心"=Person、"生态"=Product、"协议"=Person、"投资"=Person。

### Reproduction
```
# 台积电搜索中：
"台南" → Person (应为 Location/Geography)
"一季度" → Person (应为 TimePeriod/Concept)
"销售额" → Person (应为 Metric/FinancialConcept)
"高性能计算" → Person (应为 Technology/Concept)

# 英伟达搜索中：
"生态" → Product (应为 Concept)
"协议" → Person (应为 Document/Concept)
"投资" → Person (应为 Activity/Concept)
"股权" → Person (应为 FinancialConcept)

# ASML搜索中：
"数据中心" → Person (应为 Facility/Concept)
```

### Expected Behavior
LLM 实体提取阶段应有受控词表约束 entity_type 分类。非人名实体不应标注为 Person。

### Impact
MEDIUM。与 F20260509-002 和 F20260509-017 同根问题。在芯片行业搜索中问题更加突出——"台南"、"一季度"、"销售额"被标注为 Person 严重影响实体类型可信度。如果 AI 应用依赖 entity_type 过滤人物相关 KU，会产生大量误匹配。

---

## F20260510-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Persona** | casual |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Severity** | LOW |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | #11 |

### Summary
英伟达搜索中 KU1"英伟达投资覆盖上市公司和私营企业"和 KU2"英伟达2026年股权投资已突破400亿美元"来自同一新闻源（东方财富快讯 em_202605093732273897），描述同一事件的不同角度。

### Reproduction
```
KU1: ku_701566ece5b9d452, summary="英伟达投资覆盖上市公司和私营企业", cluster=clu_674010be0eae
KU2: ku_11b91d463e3d8f5d, summary="英伟达2026年股权投资已突破400亿美元", cluster=clu_77b4c64b0bfd
```
两个 KU 来自同一 doc_id，同一 evidence text："数据显示，今年英伟达股权投资已突破400亿美元，覆盖上市公司和私营企业"。但被分配到不同的 cluster。

### Expected Behavior
同一 evidence text 的不同角度 KU 应至少被归入同一 EventCluster，或在 top-K 中只保留信息最丰富的一条。

### Impact
LOW。确认了 Defect #11（无去重）。来自同一新闻源的 2 条 KU 占据 top-2 位置，降低信息多样性。

---

## F20260511-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | S002 |
| **Severity** | HIGH |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | #5 |

### Summary
宁德时代搜索返回的 20 条 KU 中 event_time 100% 为 None (20/20)，时间线查询完全不可用。时间范围参数记录正确但无法过滤无时间 KU。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --intent ENTITY_OVERVIEW
# → total_count: 158, ku: 20, event_time None: 20/20 (100%)

PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --intent ENTITY_TIMELINE --time-range 2025-01-01:2026-05-11
# → total_count: 100, ku: 12, event_time None: 12/12 (100%)
# published_at present: 0/12
```

### Expected Behavior
1. KU 应有 event_time，至少应从 published_at 回退
2. 时间线查询不应返回所有 event_time 为 None 的结果
3. 时间范围过滤应对有 event_time 的 KU 生效

### Impact
HIGH。作为分析师查询宁德时代事件时间线，所有 KU 缺少时间信息，无法构建时间线。比之前测试的 54% 缺失率更严重——宁德时代达到 100%。时间范围过滤因所有 event_time 为 None 而无法生效。

---

## F20260511-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | S002 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #11 |

### Summary
宁德时代搜索 Top 10 KU 中 8 条关于同一"超级科技日"事件，严重挤占信息多样性。不同来源对同一事件的报道被当作独立 KU 返回。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --intent ENTITY_OVERVIEW
```
Top 10 KU 中 8 条涉及"超级科技日"：
- KU3: "宁德时代举办超级科技日活动" (type=other)
- KU4: "宁德时代将于2026年4月21日举办主题为'极域之约'的超级科技日发布会" (type=other)
- KU5: "宁德时代将在2026年'超级科技日'上带来全新的技术、产品和生态" (type=product_launch)
- KU6: "此次超级科技日将是宁德时代成立以来技术密度最高的一场发布会" (type=other)
- KU7: "宁德时代计划在2026年4月21日举办的'超级科技日'发布会上发布钠电、凝聚态、快充等相关技术产品" (type=product_launch)
- KU8: "宁德时代表示，2026年'超级科技日'是其成立以来技术密度最高的一场发布会" (type=other)
- KU9: "宁德时代将在超级科技日推出全新的技术、产品和生态" (type=product_launch)
- KU10: "宁德时代将于4月21日举办2026年'超级科技日'，主题为'极域之约'" (type=product_launch)

### Expected Behavior
同一事件的多个来源报道应在 top-K 中去重或合并。理想情况下，"超级科技日"事件在 top 10 中最多出现 2-3 条（不同角度），其余位置留给其他事件。

### Impact
HIGH。80% 的 top-K 位置被单一事件占满，分析师只能看到一个事件的重复信息。宁德时代有 158 条 KU，涵盖公司成立、股价变动、财务业绩、产能扩张等多个维度，但全部被"超级科技日"淹没。与 Defect #11（无去重）直接相关。

---

## F20260511-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | S002, S010, ad-hoc |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #15 |

### Summary
对宁德时代执行 5 种不同 intent 查询（ENTITY_OVERVIEW、ENTITY_TIMELINE、RISK_ASSESSMENT、GUARANTEE_ANALYSIS、TOPIC_RESEARCH），结果完全一致（相同的 total_count=158、相同的 top KU 排序）。不同 intent 走完全相同的检索路径。

### Reproduction
```
# 以下 5 个查询返回完全相同的结果：
knowledge-cli search --entities "宁德时代" --intent ENTITY_OVERVIEW         # total=158
knowledge-cli search --entities "宁德时代" --intent RISK_ASSESSMENT          # total=158
knowledge-cli search --entities "宁德时代" --intent GUARANTEE_ANALYSIS       # total=158
knowledge-cli search --entities "宁德时代" --intent TOPIC_RESEARCH           # total=100 (仅 time_range 不同)
knowledge-cli search --entities "宁德时代" --intent ENTITY_TIMELINE --time-range 2025-01-01:2026-05-11  # total=100
```
ENTITY_OVERVIEW 和 RISK_ASSESSMENT 的前 5 条 KU 完全一致：
1. 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
2. 中际旭创取代宁德时代成为主动权益基金第一大重仓股
3. 宁德时代举办超级科技日活动
4. 宁德时代将于2026年4月21日举办主题为'极域之约'的超级科技日发布会
5. 宁德时代将在2026年'超级科技日'上带来全新的技术、产品和生态

### Expected Behavior
RISK_ASSESSMENT 应优先返回风险相关内容（股价下跌、监管风险、供应链风险等）；GUARANTEE_ANALYSIS 应聚焦担保相关内容；TOPIC_RESEARCH 应返回行业级分析。不同 intent 应产出不同的排序或过滤策略。

### Impact
HIGH。确认 F20260509-021 在宁德时代依然存在。所有 intent 产出的结果完全相同，AI 应用依赖不同 intent 获取不同维度信息的期望完全落空。

---

## F20260511-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | S007 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #5 |

### Summary
时间范围过滤在宁德时代上部分生效——total_count 随范围变化（无范围=158, 2026-01月=61, 宽范围=158），但返回的 top-20 KU 因全部 event_time=None 而完全不受过滤影响。反向范围正确返回 0 结果。

### Reproduction
```
# 无范围
total=158, ku=20

# 窄范围 (2026-01-01:2026-01-31)
total=61, ku=20  # total 减少 61%，但返回的 KU 与无范围相同

# 宽范围 (2025-01-01:2026-05-11)
total=158, ku=20  # 与无范围完全一致

# 零长度 (2026-01-01:2026-01-01)
total=61, ku=20   # 无崩溃，无错误提示

# 反向范围 (2026-05-11:2025-01-01)
total=0, ku=0     # 正确返回空，但无错误提示
```

对比之前 F20260510-002（英伟达）：英伟达测试中 total 几乎不变（52-64），而宁德时代 total 从 158→61。说明时间范围过滤对 total_count（BM25 候选集）有部分效果，但因返回的 KU 全部 event_time=None，过滤无法作用于它们。

### Expected Behavior
1. 有 event_time 的 KU 应被正确过滤
2. event_time=None 的 KU 应使用 published_at 作为回退，或被排除在时间范围查询之外
3. 零长度范围应返回 0 结果或明确提示
4. 反向范围应有错误提示

### Impact
HIGH。分析师搜索"宁德时代 2026 年 1 月事件"获得与全量搜索完全相同的结果，时间维度完全失效。部分改善（total_count 变化）说明底层过滤逻辑存在，但因 event_time 缺失率 100% 导致无法作用于宁德时代。

---

## F20260511-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (CATL alias) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #1 (partial) |

### Summary
"宁德"简称解析到独立实体"宁德"(Company, ent_8cbb8b13b38c)，而非宁德时代(ent_85272d28e621)。搜索返回的 20 条 KU 中仅 2 条提及宁德时代，用户体验严重降级。对比"CALI"英文别名正确解析到宁德时代。

### Reproduction
```
# "宁德时代" → matched_entity_ids: ['ent_85272d28e621'], total=158
# "CATL" → matched_entity_ids: ['ent_85272d28e621'], total=160  ✅ 英文别名正确

# "宁德" → matched_entity_ids: ['ent_8cbb8b13b38c'], total=61  ❌ 解析到不同实体
# Entity detail: canonical_name="宁德", entity_type="Company"
# KUs with 宁德时代: 2/20
# KUs with only 宁德: 1/20
# Top KU: "宁德创历史新高" (可能是宁德时代股票的简称)
```

### Expected Behavior
"宁德"应通过实体解析别名机制关联到"宁德时代"（宁德时代的常见简称之一）。或者至少应有松弛策略——当精确匹配到实体"宁德"但结果较少时，尝试扩展到包含"宁德"的实体（如"宁德时代"）。

### Impact
HIGH。中文简称在小米（"小米"→小米集团 ✅）、腾讯（"腾讯"→腾讯控股 ✅）上工作正常，但在宁德时代上失败。实体别名覆盖不完整，分析师使用常见简称时会得到错误的结果集。

---

## F20260511-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (relationship query) |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #12 |

### Summary
RELATIONSHIP_QUERY 查询宁德时代→比亚迪返回 graph_nodes=0, graph_edges=0，尽管 graph_used=True、Neo4j 正在运行。candidate_count=0 说明图谱遍历完全找不到两个实体之间的路径。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --intent RELATIONSHIP_QUERY --target-entity "比亚迪" --hops 2
```
- graph_enabled: True
- graph_used: True
- candidate_count: 0
- expanded_cluster_count: 0
- expanded_entity_count: 0
- graph_data nodes: 0
- graph_data edges: 0
- errors: []
- target_entity in query: "比亚迪"

对比 ENTITY_OVERVIEW 的图增强：
- candidate_count: 91
- expanded_cluster_count: 91
- expanded_entity_count: 100
- graph_data nodes: 192
- graph_data edges: 246

### Expected Behavior
宁德时代和比亚迪作为动力电池行业最重要的两家企业，应有图谱路径（供应链关系、竞争关系、合作历史等）。即使 2-hop 无法直接连接，至少 1-hop 的邻居应有交集。

### Impact
HIGH。关系查询是分析师核心需求之一。Neo4j 正在运行且单实体图增强工作正常（192 nodes），但两个实体之间的关系查询返回完全空的图。图谱中的关系边类型只有 INVOLVED_IN（Entity→EventCluster），缺少 Entity→Entity 直接关系，导致多跳遍历无法跨越。

---

## F20260511-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (event type filter) |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #2 |

### Summary
event_type 过滤 "product_launch" 将 total_count 从 158 减少到 65，但返回的 KU 中仍包含 company_establishment、market_analysis、business_strategy 等非匹配类型。过滤不严格，混入其他类型。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --event-types "product_launch"
# → total: 65, ku: 20
# unit_types in results: {industry_analysis, product_launch, business_strategy, company_establishment, market_analysis}
# All match product_launch: False
# KU1 type=company_establishment (不匹配)

# 中文 "产品发布"
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" --event-types "产品发布"
# → total: 65 (与英文相同)
# unit_types: {stock_price_change, sector_performance, financial_performance, ...}
```

### Expected Behavior
指定 event_type 过滤后，返回的 KU 应只包含匹配的 unit_type。当前 total_count 变化说明过滤在 BM25 层面生效，但后续排序或截断阶段混入了不匹配的 KU。

### Impact
MEDIUM。分析师按事件类型过滤时，得到的结果包含不相关类型，降低过滤的可信度。中文"产品发布"返回与英文"product_launch"相同的 total_count (65) 是一个积极信号，说明中英文映射部分生效。

---

## F20260511-008

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Persona** | analyst |
| **Scenario** | ad-hoc (CATL vs BYD) |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | IMPROVED |
| **Related Defect** | #15 |

### Summary
COMPARATIVE_ANALYSIS 宁德时代 vs 比亚迪对比之前有显著改善：宁德时代 15 条、比亚迪 5 条（之前 20:0）。但仍无 KU 同时提及两个实体，排序前 6 条中 4 条为比亚迪（被推到前面），后面全是宁德时代。

### Reproduction
```
PYTHONIOENCODING=utf-8 uv run knowledge-cli search --entities "宁德时代" "比亚迪" --intent COMPARATIVE_ANALYSIS
# → total: 83, ku: 20
# 宁德时代 in KU: 15/20 (75%)
# 比亚迪 in KU: 5/20 (25%)
# Both in same KU: 0/20 (0%)
# KU3-KU6 全部是比亚迪（辟谣/否认传言/神州租车合作）
# KU7-KU20 全部是宁德时代（超级科技日）
```

### Expected Behavior
1. 两个实体应均衡覆盖（至少各占 30%+）
2. 应优先返回同时提及两个实体的 KU（如比亚迪使用宁德时代电池的合作报道）
3. 排序应交替穿插两个实体的信息，而非按实体分块

### Impact
MEDIUM。对比 F20260509-010（宁德时代:比亚迪 = 20:0），当前 15:5 是显著改善。coverage_bonus 策略生效。但 0 条 KU 同时提及两个实体意味着系统无法找到两者的直接关联信息，对比分析仍然只是"并列展示"而非"对比分析"。

## F20260516-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011 |
| **Severity** | MEDIUM |
| **Category** | schema |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
top-k=0 返回不一致结果：total_count=60 但 knowledge_units=[]，同时 entities 仍被返回（1个）。程序化调用者无法区分"top-k=0故不返回KU"和"确实无结果"。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --top-k 0
```
返回: total_count=60, knowledge_units=[], entities=[1个], errors=[], warnings=[]

### Expected Behavior
top-k=0 应该被验证为无效输入并返回明确的错误/警告（如 "INVALID_TOP_K: top-k must be >= 1"），或返回 total_count=0。不应返回 total_count=60 但 KU 为空的不一致状态。

### Impact
作为 Agent 开发者，我依赖 total_count 判断是否有数据。top-k=0 时 total_count=60 会让我误以为有数据可获取，导致逻辑错误。

---

## F20260516-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011 |
| **Severity** | MEDIUM |
| **Category** | error-handling |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
负数 top-k（如 -1）被静默接受并等同于"无限制"——返回全部 59 条 KU。无任何输入验证或警告。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --top-k -1
```
返回: total_count=60, knowledge_units=[59条], errors=[], warnings=[]

### Expected Behavior
负数 top-k 应触发输入验证错误（如 "INVALID_TOP_K: top-k must be >= 1"），或至少在 warnings 中提示。不应静默忽略并返回全部结果。

### Impact
API 集成中如果 top-k 参数计算错误为负数，系统会返回大量非预期结果，消耗不必要的带宽和计算资源。

---

## F20260516-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011 |
| **Severity** | HIGH |
| **Category** | error-handling |
| **Status** | OPEN |
| **Related Defect** | #12 |

### Summary
--hops 5 导致命令无限挂起（>4分钟无响应），必须手动终止。无超时保护。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --hops 5
```
命令运行 >4 分钟无输出，必须 kill 进程。

### Expected Behavior
系统应对 hops 值有上限约束（如 max 3），或对图遍历设置全局超时（如 30 秒）。极高的 hops 值不应导致无限遍历。

### Impact
Agent 集成中如果自动设置了高 hops 值，会导致请求永久挂起，阻塞调用链。无超时保护意味着无法恢复。

---

## F20260516-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011 |
| **Severity** | LOW |
| **Category** | ux |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
不带 --entities 参数调用 search 返回空结果且无任何警告/错误提示，而 --entities "" 有 ENTITY_NOT_FOUND 和 NO_RESULTS 警告。行为不一致。

### Reproduction
```
uv run knowledge-cli search          # entities=[], warnings=[], errors=[]
uv run knowledge-cli search --entities ""  # entities=[""], warnings=[ENTITY_NOT_FOUND, NO_RESULTS]
```

### Expected Behavior
两者都应给出一致的提示。不带 --entities 参数时应有 "NO_ENTITIES_PROVIDED" 警告。

### Impact
开发者可能不带 entities 参数调用并困惑于无结果且无提示。

---

## F20260516-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S012 |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #2 |

### Summary
event_types 过滤完全无效。请求 debt_default 过滤返回 20 条 KU 中仅 1 条匹配；请求"债务违约"返回 20 条 KU 中 0 条匹配。过滤值被记录在 applied_filters 中但实际未生效。

### Reproduction
```
uv run knowledge-cli search --entities "恒大集团" --event-types "debt_default"
```
返回 total_count=61, KU=20, 其中仅 1 条 unit_type="debt_default"（1/20=5%）

```
uv run knowledge-cli search --entities "恒大集团" --event-types "债务违约"
```
返回 total_count=60, KU=20, 其中 0 条 unit_type 含"违约"（0/20=0%）

### Expected Behavior
event_types 过滤应只返回 unit_type 匹配的 KU。debt_default 过滤应全部返回 debt_default 类型。

### Impact
分析师依赖事件类型过滤缩小范围，但结果完全不受过滤影响，等同于无过滤。Agent 集成中带 event_types 参数的调用全部无效。确认 Defect #2 仍然存在。

---

## F20260516-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S012 (ad-hoc) |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #5 |

### Summary
time_range 过滤完全无效。查询 2025 年和 2026 年 4 月的小米集团数据返回完全相同的结果集（相同 KU ID、相同排序、相同日期）。

### Reproduction
```
uv run knowledge-cli search --entities "小米集团" --time-range "2026-04-01:2026-04-30"
```
返回 total_count=60, KU=20

```
uv run knowledge-cli search --entities "小米集团" --time-range "2025-01-01:2025-12-31"
```
返回 total_count=60, KU=20 — **与 2026-04 完全相同**，包括同一 KU ID 和排序。

Top 3 KU 两组完全一致:
1. ku_f5868c0f8b8f257f: event_time=2026-04-09 (2026年数据出现在2025年查询中)
2. ku_363e499517c66118: event_time=None
3. ku_e6fd9ace2076c7d6: event_time=2026-04-13

### Expected Behavior
time_range 应过滤掉不在指定时间范围内的 KU。2025 年查询不应返回 2026 年的数据。

### Impact
时间线查询和时间范围过滤完全不可用。分析师无法按时间缩小范围，Agent 无法实现时间维度的数据切片。与 F20260510-004 和 F20260511-003 一致，持续未修复。

---

## F20260516-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S012 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #1, #3 |

### Summary
搜索完全虚构的实体"不存在公司XYZ123"，BM25 回退返回 118 条结果（top 20 中全是无关内容），且无任何警告提示"实体未找到"。对比 --entities "" 会给出 ENTITY_NOT_FOUND 警告。

### Reproduction
```
uv run knowledge-cli search --entities "不存在公司XYZ123"
```
返回 total_count=118, KU=20, matched_entity_ids=[], warnings=[], errors=[]

Top 3 KU 完全无关:
1. ku_ae64c071e007526d: 公司关于股东实际控制人... (璟鸿科技)
2. ku_41d291baecea2ae7: *ST黑猫股票... (ST黑猫)
3. ku_49e13a929ec0d362: 苏州新海宜... (新海宜)

### Expected Behavior
当实体未找到且 BM25 回退结果明显不相关时，应有警告 "ENTITY_NOT_FOUND" 和/或 "LOW_RELEVANCE_RESULTS"。total_count=118 给人虚假的"找到很多结果"印象。

### Impact
Agent 集成中如果依赖 total_count > 0 判断查询成功，会被 118 条完全无关的结果误导。与 --entities "" 的行为（有警告）不一致。

---

## F20260516-008

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011, S012 |
| **Severity** | MEDIUM |
| **Category** | error-handling |
| **Status** | OPEN |
| **Related Defect** | #12 |

### Summary
Neo4j 在每次查询中发出警告：property `primary_entity_id` does not exist in database。这是代码中使用的属性名与 Neo4j 数据库 schema 不匹配。

### Reproduction
每次带图谱的查询都会在 stderr 输出:
```
warn: property key does not exist. The property `primary_entity_id` does not exist in database `neo4j`.
```
对应 Cypher 查询中的 `cluster.primary_entity_id AS cluster_primary_entity_id`。

### Expected Behavior
Neo4j schema 应与代码预期一致，或代码应处理属性不存在的情况。

### Impact
(1) stderr 被大量重复警告污染，影响日志监控。(2) 图谱查询中 primary_entity_id 始终为 null，可能影响 cluster 补全逻辑。(3) 代码与 schema 不同步表明图谱功能有遗留问题。

---

## F20260516-009

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Persona** | developer |
| **Scenario** | S011, S012 |
| **Severity** | MEDIUM |
| **Category** | output-quality |
| **Status** | OPEN |
| **Related Defect** | - |

### Summary
jieba 分词器初始化日志输出到 stdout（而非 stderr），污染 JSON 输出。输出中混合了 "Building prefix dict..."、"Loading model..."、"Prefix dict has been built successfully." 等消息。

### Reproduction
```
uv run knowledge-cli search --entities "不存在公司XYZ123" 2>/dev/null
```
输出前 4 行为 jieba 日志，后跟 JSON。

### Expected Behavior
库加载日志应输出到 stderr，或完全抑制（使用 logging 模块而非 print）。stdout 应仅包含 JSON 结果。

### Impact
Agent 集成中 pipe stdout 到 JSON parser 会因混合内容而解析失败。必须额外的文本过滤步骤才能正确解析输出。

---

## F20260520-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Persona** | casual |
| **Scenario** | S007 |
| **Severity** | CRITICAL |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #5 |

### Summary
时间范围过滤已修复——之前所有时间范围返回完全相同的结果（F20260516-006, F20260510-002），现在不同时间范围正确返回不同结果子集。

### Reproduction
```
# 无范围
uv run knowledge-cli search --entities "小米集团"
# → total=60, ku=20

# 2026-04 窄范围
uv run knowledge-cli search --entities "小米集团" --time-range "2026-04-01:2026-04-30"
# → total=47, ku=20, 所有13条有日期的KU均在2026-04 ✅

# 2025全年
uv run knowledge-cli search --entities "小米集团" --time-range "2025-01-01:2025-12-31"
# → total=1, ku=1 ✅ (之前返回 total=60 完全相同)

# 2026-01 窄范围
uv run knowledge-cli search --entities "小米集团" --time-range "2026-01-01:2026-01-31"
# → total=3, ku=3 ✅

# 反向范围
uv run knowledge-cli search --entities "小米集团" --time-range "2026-04-13:2025-01-01"
# → total=0, ku=0, warnings=[NO_RESULTS] ✅
```

### Expected Behavior
时间范围过滤应正确过滤结果。已修复，行为正确。

### Impact
Defect #5 已修复。分析师和商务用户现在可以按时间缩小搜索范围，时间线查询变得可用。反向范围有 NO_RESULTS 警告，零长度范围不崩溃。

---

## F20260520-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Persona** | casual |
| **Scenario** | S006 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | FIXED |
| **Related Defect** | #1, #16 |

### Summary
BYD 英文别名搜索已修复——之前返回 0 条（F20260509-015），现在返回 64 条且内容全部关于比亚迪。中文简称全部正常工作。

### Reproduction
```
# 英文别名 BYD → 之前 0 条，现在 64 条
uv run knowledge-cli search --entities "BYD" --intent ENTITY_OVERVIEW
# → total=64, ku=20, bm25=64
# KU1: "比亚迪与神州租车在深圳签署闪充中国战略合作暨10万台采购框架协议"
# KU2: "比亚迪与肯德基在深圳签署战略合作协议"
# KU3: "比亚迪成功注册'比亚迪闪充'商标"

# 中文简称对比
# "小米集团" → total=60
# "小米" → total=62 (差异 3.3%)
# "腾讯" → total=66
# "字节跳动" → total=60
# "恒大" → total=60 (之前仅 1 条!)
```

### Expected Behavior
英文别名和中文简称应正确解析到目标实体。已修复，所有简称均正常工作。

### Impact
显著改善。casual 商务用户可以用简称或英文名搜索公司，不再需要记忆精确全名。BYD 修复确认实体解析改善；"恒大"从 1 条增加到 60 条说明数据覆盖也有扩展。

---

## F20260520-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Persona** | casual |
| **Scenario** | S013 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | IMPROVED |
| **Related Defect** | #1, #3, #16 |

### Summary
BM25 回退对话题搜索显著改善——之前"量化交易"(0条)、"供应链金融"(0条)、"芯片制裁"(0条)、"光刻"(0条) 全部返回空结果（F20260509-016, F20260510-005），现在均返回结果。但精确度仍然受限（Defect #3 FTS5 中文分词）。

### Reproduction
```
# 之前 0 条 → 现在有结果
# 量化交易: total=60, ku=20 (4/20=20% 真正相关)
# 供应链金融: total=60, ku=20 (相关性较好)
# 芯片制裁: total=91, ku=20 (主要匹配"芯片"token, 非精准"芯片制裁")
# 光刻: total=60, ku=20 (结果高相关: 光刻机概念股, 光刻胶制备)

# 已知有实体的话题也改善
# 半导体: 19→45 条
# 大模型: 16→20 条
# 新能源汽车: 40 条
```

"量化交易"精确度分析：20 条中仅 4 条真正相关（"程序化交易暂停"、"量化策略"等）。其余为"沃什交易"、"关联交易"等包含"交易"token 的无关结果。

### Expected Behavior
话题搜索应返回高度相关的结果。当前 BM25 回退能找到候选，但 token 级匹配导致精确度低。理想情况下应实现语义匹配或中文分词。

### Impact
IMPROVED。从"完全无结果"到"有结果但需筛选"，对 casual 用户是重大改善。至少用户可以看到一些相关内容，而不会面临令人沮丧的 0 结果页面。Defect #3（FTS5 中文分词）仍是精确度瓶颈。

---

## F20260520-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Persona** | casual |
| **Scenario** | S013 (ad-hoc) |
| **Severity** | MEDIUM |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #3 |

### Summary
"海思"搜索仍返回 0/20 条华为海思相关结果（与 F20260510-001 一致）。BM25 将"海思"token 匹配到海思科（药企）、海信等不相关公司。60 条结果中可能 1 条提及海思合作，但整体仍然被噪声占满。

### Reproduction
```
uv run knowledge-cli search --entities "海思" --intent ENTITY_OVERVIEW
# → total=60, ku=20
# KU1: "高新兴车载前装车规模组产品与海思合作" (可能相关)
# KU2: "海思科连发三份重磅公告" (海思科药企, 无关)
# KU3: "海思科一季度净利润超过去年全年" (海思科药企, 无关)
```

### Expected Behavior
"海思"应解析到华为海思半导体（HiSilicon），至少应将华为芯片相关的 KU 排在前面。当前 BM25 短 token 碰撞问题未解决。

### Impact
MEDIUM。确认 F20260510-001 仍然存在。对芯片行业分析师和商务用户，搜索"海思"得不到正确结果。2 字短实体名的 BM25 碰撞问题持续影响检索质量。

---

## F20260520-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Persona** | casual |
| **Scenario** | S004 |
| **Severity** | HIGH |
| **Category** | retrieval-accuracy |
| **Status** | OPEN |
| **Related Defect** | #1, #16 |

### Summary
搜索完全不存在的实体"完全不存在的公司名称XYZ"仍返回 117 条结果（与 F20260516-007 一致），0/20 条提及 XYZ，无任何警告。BM25 将"公司"、"名称"等常见 token 匹配到大量无关内容。

### Reproduction
```
uv run knowledge-cli search --entities "完全不存在的公司名称XYZ"
# → total=117, ku=20, errors=[], warnings=[]
# matched_entity_ids: [] (空)
# KU1: "公司、控股股东不存在应披露而未披露的重大事项" (匹配"公司")
# KU2: "北京贾国龙空气馍餐饮管理公司更名" (匹配"公司")
# 0/20 KUs mention "XYZ"
```

### Expected Behavior
当实体未找到且 BM25 结果明显不相关时，应提供警告（如"ENTITY_NOT_FOUND"、"LOW_RELEVANCE"）。total_count=117 给用户虚假的"找到很多"印象。

### Impact
HIGH。确认 F20260516-007 未改善。casual 用户看到 117 条结果会以为找到了信息，实际全部无关。对 AI 应用集成更严重——依赖 total_count>0 判断成功的逻辑会被误导。
