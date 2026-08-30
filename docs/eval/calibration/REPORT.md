# ScoringProfile 权重标定报告（Phase 1）

> 对 `src/retrieval/scoring.py` 的 `INTENT_PROFILES` 做一次数据驱动的权重标定，
> 利用现有 `docs/eval/` 闭环（固定 eval set + 冻结 DB 快照 + judge cache），
> 在不调任何 LLM 的前提下量化每个权重项对排序质量的影响，并为 Phase 2/3 决策提供依据。

> **⚠ 2026-08-30 加注（双路线重构后）**：`knowledge_search.py` 已重构为实体/文本双路线
> （`feat/retrieval-clean-routes`）。`_score_final_hit` 加权融合仍保留，但其角色变为
> ① reranker 之前的候选排序、② reranker 不可用时的降级顺序、③ hit_scores 元数据来源；
> 本报告引用的行号（`knowledge_search.py:846-877`）已失效，`rerank.py` harness 的
> 复现基线需重新采集信号后才能用于新架构。报告中的权重敏感性结论仅描述降级路径
> （无 reranker 时）的行为。

## 0. 方法与可信度

**Harness**（`docs/eval/calibration/`，纯 Python，不碰 `src/`）：
1. `collect_signals.py` —— 对 30 条 query 跑一次 `run_pipeline`（仅 sqlite+FAISS，无 LLM），从 `result.retrieval.hit_scores` 抽取每个候选 KU 的**原始信号**（`bm25_raw`/`dense_raw`/`entity_hit`/`event_type_hit`/`anchor_ts`/`cluster_id`），缓存到 `component_signals.json`。
2. `rerank.py` —— 闭式重算 `final_score`（公式与 `knowledge_search.py:846-877` 逐行对应）+ 复现完整排序管线（`sort(score,ts,ku_id) → _diversify_by_cluster(≤3) → truncate`）。
3. 复用 `v1_labels.json`（1922 labels）+ `docs.eval.scripts.metrics.compute_query_metrics`（纯函数）。

**正确性 Gate（已通过）**：`reproduce_baseline.py` 用默认权重重排，**所有 6 个 macro 指标 + 6 个 per-category nDCG + 28 个 per-query nDCG 全部在 ±0.01 内匹配** `results/20260702_110009_report.txt`（nDCG@10=0.6336）。证明重排引擎忠实复现生产打分。

**已知局限**（pool-stable 近似）：重排在"已 judge 的候选池"内只改顺序、不改成员，因此精确测**排序质量**，但忽略"换权重后召回候选会变"。任何落地的新权重都**必须再跑一次真实 `run_eval` 复核**。28 query 统计薄，所有 ΔnDCG 均附 bootstrap 95% CI。

---

## 1. 核心发现：4/6 权重项在当前配置下完全惰性

单变量敏感性扫描（`sensitivity.py`）显示一个出乎意料但**数据铁证**的结果：

| 权重项 | 扫描范围 | nDCG@10 是否变化 | 结论 |
|---|---|---|---|
| `entity_bonus` | 0 → 20 | **0 → 0**（完全不变） | 🔴 惰性 |
| `dense_weight` | 0 → 16 | **0 → 0**（完全不变） | 🔴 惰性 |
| `event_type_bonus` | 0 → 8 | **0 → 0**（完全不变） | 🔴 惰性 |
| `recency_scale` | 0 → 10000 | **0 → 0**（完全不变） | 🔴 惰性 |
| `bm25_weight` | 0 → 1.5 | 0.6336 → 0.6689 | 🟢 **唯一活跃杠杆 1** |
| `bm25_cap` | 0 → 10 | 0.6336 → 0.6689 | 🟢 **唯一活跃杠杆 2** |

### 为什么 4 项惰性？（`inspect_signals.py` 诊断）

对 1631 个候选信号统计：

| 信号 | 命中情况 | 后果 |
|---|---|---|
| `dense_raw > 0` | **0/1631 (0%)** | dense 路径**从未触发** → `dense_weight` 无对象可加权。根因：snapshot DB 无 embedding 配置（`OPENAI_EMBEDDING_API_KEY` 等未注入），`KnowledgeSearcher` 静默降级为纯 BM25。 |
| `entity_hit` | 1131/1631 (69%)，**但每个 query 内 top-10 全部为 True** | recall 是按 entity-id 精确匹配召回的，**池内候选必然命中实体** → `entity_bonus` 对池内**每个候选都是同一个常数**，加常数不改变相对排序。0/28 query 在 top-10 内有 entity_hit 差异。 |
| `event_type_hit` | 4/1631 (0.2%) | 几乎不触发 → 几乎无影响。 |
| `recency` | `ts/1e13` ≈ 1.8e-4，比 entity_bonus(10) 小 5 个数量级 | 即使 `recency_scale=10000`，与常数 entity_bonus(10) 叠加后仍不足以越过任何 entity_hit 候选，故对 top-10 排序无影响。 |

**一句话**：在当前配置下，**整个排序实际上只由 BM25 + 时间戳 tie-break 驱动**。`entity_bonus=10` 看似主导，实则因池内全 True 而退化为常数偏移，不参与判别。

### 这对最初诊断的影响

上一轮分析指出"entity_bonus 二元化、权重未标定"——**结构性诊断仍然成立**，但惰性的**具体根因更深层**：不是"权重没调好"，而是**dense 被关掉 + 池内 entity 命中同质**。这意味着：仅靠调权重（Phase 1 目标）能撬动的增益很有限，真正的大头在 Phase 2/3（见 §4）。

---

## 2. 活跃杠杆的标定结果

### 单变量（`sensitivity.py`）

`bm25_weight` 在 0.2 达峰（0.6689，+0.0353），但 0.5 回落到 0.6419，≥0.8 又回到 0.6336（非单调，因 cap 截断交互）。
`bm25_cap` 在 ≥4 达峰（0.6689），cap=3（当前默认）处于次优。

### 网格搜索（`grid_search.py`，bm25_weight × bm25_cap）

```
Top: bm25_weight∈{0.1,0.2} × bm25_cap≥3  →  nDCG=0.6689 (+0.0353)  R@20=0.4616  P@5=0.6786
基线（per-intent）                                    nDCG=0.6336            R@20=0.4483  P@5=0.6571
```

**特征**：低 `bm25_weight` + 不设上限（cap≥3 即饱和）成平台。语义：当前实现把 BM25 "加权后硬截断到 cap"，而最优区是把 BM25 当作**低权重、不截断**的弱信号。等价于让原始 BM25 的连续梯度更完整地传递到排序，而非被 cap 拍平。

### 统计显著性（bootstrap 95% CI，1000 次重采样）

| 配置 | nDCG@10 | 95% CI |
|---|---|---|
| 最优 (bm25_w=0.1, cap=3) | 0.6689 | [0.5290, 0.7977] |
| 基线 (per-intent) | 0.6336 | [0.4948, 0.7696] |

**CI 严重重叠**：+0.0353 的提升**在 28-query 噪声范围内，不具统计显著性**。这是诚实结论——不能仅凭此就把权重落地。但方向一致、CI 中位数上移，配合"活跃杠杆唯一性"的强先验，**建议作为低风险微调采纳，并扩大 eval set 后复测**。

---

## 3. 建议的最优 Profile

仅对**活跃维度**调整，其余保持默认（因惰性，改了也无效；且 dense/event 一旦启用需重新标定）：

| Intent | `bm25_weight` | `bm25_cap` | 其余 | 说明 |
|---|---|---|---|---|
| `ENTITY_OVERVIEW` | **0.2** | **4.0**（或直接去掉 cap） | 默认 | 主力场景，网格最优点 |
| `TOPIC_RESEARCH` | **0.3** | **4.0** | 默认 | topic 无实体，BM25 是主信号，略高权重 |
| `EVENT_ANALYSIS` | **0.2** | **3.5** | 默认 | 维持现状量级 |
| `RELATIONSHIP_QUERY` | **0.2** | **4.0** | 默认 | 维持 |
| `COMPARATIVE_ANALYSIS` / `ENTITY_TIMELINE` | — | — | — | 结构化排序，权重无效，不改 |

**预期 ΔnDCG ≈ +0.035**（需真实 `run_eval` 复核，见局限）。

> 注：建议**移除 `bm25_cap` 或设到 ∞**。cap 的工程意义是"防止某条 BM25 极高分独占排序"，但实测最优区恰是 cap 不起作用的区域；且 entity_bonus 作为池内常数已无压制 BM25 的必要。若担心极端值，可保留一个**高 cap（如 10）**作护栏。

---

## 4. Phase 2 / Phase 3 决策依据

本次标定**量化了原诊断的优先级**：

### Phase 3（对称 dense 索引重建）—— **优先级显著提升 🔺**
- 实测 `dense_raw>0` 占比 **0%**，即 dense 路径**完全没在工作**。这是比"嵌入不对称"更严重的问题：**整条语义召回链路是关的**。
- 一旦 dense 启用，`dense_weight` 将从惰性转为活跃，**可用同一 harness 重新标定**（重跑 `collect_signals.py` 即可，因信号缓存会自动包含新的 dense 值）。
- **预期增益最大**：comparative（0.252）、topic_no_entity（0.340）这两个最弱类目恰恰是 BM25 最吃力、最需要语义召回的场景；dense 复活后它们的上限空间最大。
- 代价：需 embedding API 配额（~674 批次，见之前讨论）。

### Phase 2（分级 entity_bonus）—— **优先级下调 🔻，且需重构 eval**
- 实测池内 top-10 entity_hit **100% 同质**，分级（按命中实体数加权）**在当前池里同样无法产生判别**——因为分母（命中数差异）几乎不存在。
- 根因：recall 是 entity-id 精确匹配召回，**召回即命中**，故池内无"部分命中"梯度。
- **若要让分级有效，必须先改变 recall 策略**：让候选池包含"主题相关但未精确匹配实体"的 KU（例如 dense 召回、或宽松别名匹配），这样池内才会有 entity_hit 的梯度，分级 bonus 才有判别对象。
- **结论**：Phase 2 的前置依赖其实是 Phase 3（dense 启用）+ 召回策略放宽。单独做 Phase 2 无收益。**建议合并到 Phase 3 之后一起评估**。

### 综合建议
1. **先落地 Phase 1 的 bm25 微调**（低风险，+0.035，CI 虽重叠但方向稳）。
2. **Phase 3（dense 复活）是下一个最高价值动作**——它把一个目前 0% 命中、权重完全惰性的核心子系统重新激活，并解锁后续标定空间。
3. Phase 2 推迟到 dense 启用 + 召回策略评估之后。

---

## 5. 复现命令

```bash
uv run python docs/eval/calibration/collect_signals.py      # 采集信号（一次）
uv run python docs/eval/calibration/reproduce_baseline.py   # 正确性 Gate
uv run python docs/eval/calibration/sensitivity.py          # 6 项单变量扫描
uv run python docs/eval/calibration/inspect_signals.py      # 信号分布诊断
uv run python docs/eval/calibration/grid_search.py          # 活跃杠杆网格 + bootstrap CI
```

产物：`component_signals.json` / `sensitivity.sweep.json` / `grid_search.grid.json`（均 gitignore，可重新生成）。

## 6. 局限与后续

- **Pool-stable 近似**：落地新权重后必须跑真实 `run_eval`（会重新召回 + 不重判，因 cache 命中）复核 pool 成分变化。
- **28 query 统计薄**：CI 宽。建议 eval set 扩到 ≥100 query 再下统计结论。
- **COMPARATIVE / TIMELINE 无效**：标定对它们无效，这两类的改进需改结构化策略，不在权重范畴。
- **dense 关闭是环境问题，非代码问题**：本次 harness 在无 embedding 配置的 snapshot 上运行，结果反映"dense 不可用"的现状；启用 dense 后所有结论需重跑更新。
