# Test Scenarios

结构化测试场景，覆盖全部 17 个已知缺陷和通用 UX 体验。

> 缺陷编号参考：`docs/design-issues/retrieval-accuracy-analysis.md`

---

## S001: Basic Entity Search

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | analyst, casual |
| **Defects Covered** | #1, #3, #11 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "小米集团"`
2. Verify: `total_count > 0`
3. Verify: `knowledge_units` 非空，每条有 `summary` 和 `evidence`
4. Verify: `entities` 包含匹配"小米集团"的实体
5. Verify: `event_clusters` 非空
6. Check: 结果是否多样化？同一事件是否占满 top K？

### Pass Criteria

- 返回 >= 10 knowledge units
- 实体正确解析
- 同一事件不超过 30% 结果

---

## S002: Entity Timeline Query

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | analyst |
| **Defects Covered** | #1, #3, #5 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "小米集团" --intent ENTITY_TIMELINE --time-range 2025-04-01:2026-04-13`
2. Verify: 所有返回的 KU 日期在指定时间范围内
3. Verify: 多个不同时间点被覆盖
4. Check: 时间线上是否有不合理的空白？

### Pass Criteria

- 所有 KU 日期在范围内
- 至少 3 个不同时间点

---

## S003: Relationship Query

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | analyst |
| **Defects Covered** | #9, #12 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "小米集团" --intent RELATIONSHIP_QUERY --target-entity "腾讯控股" --hops 2`
2. Verify: `graph_data` 部分存在且非空
3. Verify: 两个实体都出现在 graph nodes 中
4. Verify: 至少一条路径连接两个实体
5. Check: 路径上是否有中间实体？

### Pass Criteria

- graph_data 返回非空
- 两个查询实体都出现在结果中
- 至少发现一条连接路径

---

## S004: Non-existent Entity

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | developer, casual |
| **Defects Covered** | #1, #16 |
| **Estimated Time** | 3 min |

### Steps

1. Run: `knowledge-cli search --entities "完全不存在的公司名称XYZ"`
2. Verify: 输出是合法 JSON（无崩溃）
3. Verify: `total_count == 0`
4. Verify: `errors` 为空或包含提示性信息
5. Check: 是否有关于"为什么结果为空"的说明？

### Pass Criteria

- 无崩溃或乱码输出
- 空结果但 JSON 结构完整
- 理想情况有"实体未找到"提示

---

## S005: Event Type Filter

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | analyst |
| **Defects Covered** | #2 |
| **Estimated Time** | 5 min |

### Steps

1. 先不加过滤：`knowledge-cli search --entities "恒大集团" --intent ENTITY_OVERVIEW`
2. 记下结果中的 `unit_type` 值
3. 加中文过滤：`knowledge-cli search --entities "恒大集团" --event-types "债务违约"`
4. Check: 过滤后的结果是否都是指定类型？
5. 试英文：`knowledge-cli search --entities "恒大集团" --event-types "debt_default"`
6. Check: 英文事件类型是否匹配任何结果？

### Pass Criteria

- 中文事件类型过滤正确减少结果
- 英文事件类型测试了词表对齐问题

---

## S006: Entity Alias / Short Name

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | casual |
| **Defects Covered** | #1, #3 |
| **Estimated Time** | 5 min |

### Steps

1. 全名搜索：`knowledge-cli search --entities "小米集团" --intent ENTITY_OVERVIEW`，记录 `total_count`
2. 简称搜索：`knowledge-cli search --entities "小米" --intent ENTITY_OVERVIEW`，记录 `total_count`
3. Compare: 结果数量是否接近？
4. 再试：`knowledge-cli search --entities "比亚迪"` vs 如库中有 BYD 别名
5. 再试：`knowledge-cli search --entities "腾讯"`（简称）

### Pass Criteria

- 简称能解析到同一实体
- 结果数量相近（差异 < 20%）
- 简称不会完全失败

---

## S007: Time Range Boundary

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | developer, analyst |
| **Defects Covered** | #5 |
| **Estimated Time** | 5 min |

### Steps

1. 窄范围：`knowledge-cli search --entities "小米集团" --time-range 2026-01-01:2026-01-31`
2. 宽范围：`knowledge-cli search --entities "小米集团" --time-range 2025-01-01:2026-04-13`
3. 零长度：`knowledge-cli search --entities "小米集团" --time-range 2026-01-01:2026-01-01`
4. 反向范围：`knowledge-cli search --entities "小米集团" --time-range 2026-04-13:2025-01-01`

### Pass Criteria

- 窄范围是宽范围的子集
- 零长度范围不崩溃
- 反向范围优雅处理（空结果或明确错误）

---

## S008: Graph Toggle Comparison

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | developer |
| **Defects Covered** | #8, #12 |
| **Estimated Time** | 5 min |

### Steps

1. 开图谱：`knowledge-cli search --entities "小米集团" --graph-enabled`
2. 关图谱：`knowledge-cli search --entities "小米集团" --no-graph`
3. Compare: 开图谱是否返回更多实体和 cluster？
4. Check: `graph_data` 仅在开图谱时出现？
5. Check: `retrieval` 中 `graph_used` 元数据是否正确？

### Pass Criteria

- 开图谱 >= 关图谱的结果量
- graph 元数据准确

---

## S009: Multi-Entity Comparative Query

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | analyst |
| **Defects Covered** | #1, #9, #10 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "小米集团" "腾讯控股" --intent COMPARATIVE_ANALYSIS`
2. Verify: 两个实体都出现在结果中
3. Verify: 结果覆盖两个实体（不只是其中一个）
4. Check: 共享的 event_clusters 是否被识别？

### Pass Criteria

- 两个实体都出现在 entities 列表
- knowledge units 提及两个实体

---

## S010: Output Schema Validation

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | developer |
| **Defects Covered** | schema correctness |
| **Estimated Time** | 10 min |

### Steps

对每个 intent 执行搜索并验证输出 JSON schema：

1. `knowledge-cli search --entities "小米集团" --intent ENTITY_OVERVIEW`
2. `knowledge-cli search --entities "小米集团" --intent ENTITY_TIMELINE --time-range 2025-04-01:2026-04-13`
3. `knowledge-cli search --entities "小米集团" --intent RISK_ASSESSMENT`
4. `knowledge-cli search --entities "小米集团" --intent GUARANTEE_ANALYSIS`
5. `knowledge-cli search --entities "小米集团" --intent TOPIC_RESEARCH`

对**每个**输出验证：
- JSON 合法且可解析
- 顶层键：`request_id`, `query`, `source`, `knowledge_units`, `entities`, `event_clusters`, `total_count`, `retrieval`, `graph`, `graph_data`, `errors`
- `knowledge_units` 条目有：`ku_id`, `summary`, `unit_type`, `entities`, `evidence`
- `entities` 条目有：`entity_id`, `canonical_name`, `entity_type`
- `event_clusters` 条目有：`cluster_id`, `title`, `cluster_type`

### Pass Criteria

- 所有 intent 产出合法 JSON
- 无缺失必要键
- 无预期有数据的位置出现 null

---

## S011: Empty / Edge Case Inputs

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Personas** | developer |
| **Defects Covered** | #1, #16 |
| **Estimated Time** | 5 min |

### Steps

1. `knowledge-cli search --entities ""`（空字符串）
2. `knowledge-cli search`（无 entities 参数，如允许）
3. `knowledge-cli search --entities "小米集团" --top-k 0`
4. `knowledge-cli search --entities "小米集团" --top-k 1000`
5. `knowledge-cli search --entities "小米集团" --hops 5`

### Pass Criteria

- 任何输入都无崩溃
- 边界值优雅处理
- 无效/零 top-k 要么报错，要么返回空

---

## S012: Cross-Reference with Known Defects

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | developer, analyst |
| **Defects Covered** | #1-#17 (all) |
| **Estimated Time** | 15 min |

### Steps

对每个 P0 缺陷构造触发查询，验证缺陷是否仍然存在：

1. **Defect #1 (entity hard gate)**: 搜索一个只存在于 alias 但非 canonical_name 的实体名，观察是否返回空
2. **Defect #2 (event type vocabulary)**: 搜索英文事件类型 "equity_pledge"，检查是否匹配库中的"股权质押"
3. **Defect #3 (FTS Chinese)**: 搜索只出现在 summary 文本中（非 entity_mentions）的短语，检查能否找到
4. **Defect #9 (find_related primary only)**: 找一个有多实体的 cluster，用非主实体查询，检查 cluster 是否出现

### Pass Criteria

- 每个缺陷被确认存在或确认已修复
- 记录详细复现步骤

---

## S013: Topic Research Without Entity

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | analyst |
| **Defects Covered** | #15 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "半导体" --intent TOPIC_RESEARCH`（行业/话题，非具体公司）
2. Check: 系统是否返回相关的行业级结果？
3. Check: 还是因为"半导体"不是实体而返回空？

### Pass Criteria

- 非实体查询返回部分有用结果
- 不会完全失败

---

## S014: Event Impact Analysis

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Personas** | analyst |
| **Defects Covered** | #8, #12, #15 |
| **Estimated Time** | 5 min |

### Steps

1. Run: `knowledge-cli search --entities "恒大集团" --intent EVENT_IMPACT_ANALYSIS`
2. Verify: 结果包含"恒大集团"以外的受影响实体
3. Check: graph 路径是否展示影响传导？
4. Check: 焦点事件 cluster 是否被清晰标识？

### Pass Criteria

- 影响分析返回比查询实体更多的实体
- graph 数据展示关联

---

## S015: Consistency Across Identical Queries

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Personas** | developer |
| **Defects Covered** | #7 |
| **Estimated Time** | 3 min |

### Steps

1. Run: `knowledge-cli search --entities "小米集团" --top-k 10`
2. 保存输出
3. 完全相同的命令再运行一次
4. Compare: 两次结果是否完全一致？

### Pass Criteria

- 结果确定性（相同查询 = 相同结果）
- 排序稳定

---

## Scenario Coverage Matrix

| Scenario | Analyst | Developer | Casual | P0 Defects | P1 Defects |
|----------|---------|-----------|--------|------------|------------|
| S001     | X       |           | X      | #1,#3,#11  |            |
| S002     | X       |           |        | #1,#3,#5   |            |
| S003     | X       |           |        | #9,#12     |            |
| S004     |         | X         | X      | #1,#16     |            |
| S005     | X       |           |        | #2         |            |
| S006     |         |           | X      | #1,#3      |            |
| S007     | X       | X         |        |            | #5         |
| S008     |         | X         |        |            | #8,#12     |
| S009     | X       |           |        | #1,#9,#10  |            |
| S010     |         | X         |        |            |            |
| S011     |         | X         |        | #1,#16     |            |
| S012     | X       | X         |        | #1-#17     |            |
| S013     | X       |           |        |            | #15        |
| S014     | X       |           |        |            | #8,#12,#15 |
| S015     |         | X         |        |            | #7         |
