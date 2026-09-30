# 状态类内容治理：最小方案

> 状态：设计稿（讨论中，未实施）
> 数据基线：生产库实测 2026-09-30（65,135 篇 / 122,965 KU / 111,152 簇，窗口 2026-05-23 ~ 2026-09-03）
> 前置依赖：生产采集自 2026-09-03 停机约 4 周，需先恢复才能做上线后验证

## 执行摘要

生产库约 18.9%（23,179 条）KU 是"某股/板块涨跌多少"类状态描述，71%（16,361 条）无任何因果归因，是纯行情快照叙事。半衰期以小时计，却永久占据 FTS、向量索引、事件簇与图谱（19,075 个行情簇，88% 单例），并与 marketdata 行情工具（PR #21，实时报价 + 日K）完全重复。

**方案定位：一个补丁，不是架构工程。** 所需的架构件已经存在——原始层本就无损 append-only，状态层（marketdata）刚合入。本方案的全部常驻增量是**一个纯函数过滤模块 + 管道两处调用 + prompt 三行修改**（约 200 行含测试），加两个用完即弃的一次性脚本。无新表、无新字段、无新服务、无后台任务、无契约变更。

```rust
判定一句话：一年后再读仍是真命题的是陈述（入库）；
被下一笔报价取代的是状态（不入知识层，"涨多少"由 marketdata 承接）。
```

## 一、问题与证据（生产实测）

| 层 | 事实 |
|---|---|
| 原始 | 标题 25.8% 命中纯行情模式（盘中逐小时密度最高 46%）；`MARKET_VOLATILITY` 占 76.4% 是 `_infer_category` 兜底假象 |
| 知识 | 行情三类型（stock_price_change / price_change / sector_performance）KU 23,179 条（18.9%），含归因词仅 ~8%，纯状态 16,361 条；行情簇 19,075 个、88% 单例 |
| 关键教训 | prompt"纯涨跌不要提取 KU、必须归因"的禁令 2026-05-22 就存在（cc208d9，早于全部数据窗口），泄漏率仍 71%——**否定性 prompt 指令不可依赖，必须代码执行**。且该禁令只覆盖 stock_price_change，另两个类型没有归因要求 |

## 二、实现

### 2.1 新模块 `src/pipeline/state_filter.py`（约 150 行 + 单测）

纯函数、无外部依赖，模式定义仅此一份（管道与清理脚本共用同一实现，边界不漂移）：

```python
STATE_UNIT_TYPES = {"stock_price_change", "price_change", "sector_performance"}
MOVE_PATTERN      # 强行情词：涨/跌+数字、%、涨停/跌停/连板/拉升/走强/异动/冲高/回落/跳水…
ATTRIBUTION_PATTERN  # 归因词：因/受…影响/由于/得益于/推动/带动/消息面上…
EVENT_PATTERN     # 事件实质词：直接复用 _infer_category 的 9 组关键词（财报/并购/制裁/监管/高管/IPO/关税/地缘/供应链）

def is_state_only_document(doc) -> bool:
    # 标题命中行情模板 ∧ 正文无归因词 ∧ 无事件实质词 ∧ 短正文（四条件 AND，保守）
def is_pure_state_unit(unit) -> bool:
    # unit_type ∈ 三类型 ∧ summary/evidence 命中行情模式 ∧ 无归因词 ∧ 无事件实质词
```

两个出口（归因词 ∪ 事件实质词）保证"业绩暴雷，次日腰斩"这类隐含因果句放行。词表绑定东财模板化快讯单一文体——中文财经快讯的因果几乎总用 因/受/由于 显式标记，这是形态法成立的前提；接入自由文本源时按 `source_name` 一行判断整体关闭（形态法不适用于自由文本）。

**插入点**：`ContinuousPipeline._process_single_document`（`run()` 与 Admin 重处理的唯一咽喉）——
1. Stage 0：`is_state_only_document` 为真 → 跳过 LLM，日志记 `skipped_state`（省 ~25% 抽取 API 成本）；
2. Stage 1.5（unit_type 归一化之后、实体解析之前）：逐条 `is_pure_state_unit` 丢弃并计数（计数写入处理日志，丢弃可见，符合 fail-fast）。

配套小改动：`get_processed_doc_ids()`（knowledge_base.py:758）status 条件加 `skipped_state`；`DocumentProcessingResult.status` Literal 加同名值（`skipped_state` 可批量重置为 pending 重跑，一切可逆）。

### 2.2 prompt 修改（三行）

归因要求从 `stock_price_change` 扩到 `price_change`、`sector_performance`；补一个"整篇纯行情数字 → 返回空列表"的正例。只作引导，执行靠 2.1。

### 2.3 一次性动作（用完即弃）

1. `scripts/prune_state_kus.py`：存量清理，复用 `migrate_unit_types.py` / `prune_graph_orphans.py` 模式。dry-run 报告 → 备份 → 删 KU+FTS（两表同删，防触发 FTS 全量重建）→ 空簇删行 + `KnowledgeGraphSync.delete_node()` → FAISS 全量重建（`migrate_vectors.py` 先例）→ 用 `snapshot_eval_pair.py` 重生成 eval fixture，审计 golden 集是否含行情类期望。选择规则 = `is_pure_state_unit` 同一实现。实体不动（只输出零关联实体报告）。预估：KU -13.3%，行情空簇大半删除。**顺序：必须在 2.1 合入后执行**，否则清理窗口内继续泄漏。
2. `_infer_category` 兜底 `MARKET_VOLATILITY` → `GENERAL` + 存量一次性 UPDATE。

## 三、明确不做（简单性约束下的取舍）

| 不做 | 理由 | 何时再做 |
|---|---|---|
| `attribution` 结构化字段 + span 落地核查 | 动抽取契约/schema/payload，是本方案最大复杂度来源；KU 级正则已能止漏 | 上线后实测误杀 ≥2% 时作为预案启用 |
| 审计表 / 复判回路 | 常驻机制 + 后台任务 + Admin 页面；一条 SQL 可得同等决策信息 | 无需机制化，见 §四 |
| 检索端时间衰减 | 清理后行情 KU 仅剩 ~7k 有归因条目，边际收益不值一处排序改动 | 不做（除非未来行情类查询质量出问题） |
| 实体孤儿自动清理 | 引发 alias/图谱连锁，收益小 | 只出报告，人工定 |

持续测量用两条 SQL（可后续加进 Admin 现有 processing 视图，非新页面）：新增行情类 KU 占比（目标 <2%，基线 18.9%）；`skipped_state` 文档数与占比（预期 ~25%）。

## 四、验收

| 门槛 | 标准 |
|---|---|
| 过滤器精度（上线前，一次性人工） | 各随机抽 100 条（被判 state-only 的文档、被丢弃的 KU），误杀率 <2% |
| 上线后（一条 SQL，观察两周） | 新增行情类 KU 占比 18.9% → <2% |
| eval 回归 | 清理后 `eval_run.py` + `eval_guard.py` 通过；golden 修订走刻意演进基线更新 |
| 溯源 | 被跳过/清理的文档仍在 news_articles，Admin 可达 |

## 五、维护成本账

- 常驻增量：1 个纯函数模块 + 2 个调用点 ≈ 200 行（含测试），无状态、无 IO、无依赖；
- 唯一持续成本：行为词表，绑定单一数据源，模板漂移时改词表即可（`skipped_state` 可重置重跑消化历史）；
- 全部动作可逆：原始层永不删，误杀最坏代价是"晚入库"。

## 决策记录（待对齐）

1. 词表精度不达标的预案顺序：先调词表 → 仍不行才上 `attribution` 字段方案（见 §三）。
2. FX/商品/美股覆盖缺口：v1 直接丢弃（陈旧状态 KU 比空结果更有害）；长期由 marketdata 扩品种承接。
3. `_infer_category` 存量是否回填 GENERAL：建议回填（一次性 UPDATE，无下游 JOIN 依赖）。
