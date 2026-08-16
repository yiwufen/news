# User Testing Quality Metrics

> **已归档(2026-08-16 标注)**:本体系自 2026-05-24 后停更,质量度量基线已由 `docs/eval/`(可复现的检索质量评估)取代,对照说明见 `docs/eval/README.md`。`findings.md` 的 OPEN 项仍作为 bug 报告线索被 `.zcode/rules/retrieval-code.md` 引用。
>
> 每次测试会话结束后更新(归档前)。

---

## Overall Statistics

| Metric | Value | Last Updated |
|--------|-------|--------------|
| Total Sessions | 9 | 2026-05-24 |
| Total Scenarios Executed | 71 | 2026-05-24 |
| Total Findings | 61 | 2026-05-24 |
| CRITICAL Findings (OPEN) | 5 | 2026-08-16 * |
| CRITICAL Findings (PARTIAL) | 1 | 2026-08-16 * |
| CRITICAL Findings (FIXED) | 4 | 2026-08-16 * |
| HIGH Findings (OPEN) | 17 | 2026-08-16 * |
| HIGH Findings (IMPROVED) | 2 | 2026-08-16 * |
| HIGH Findings (FIXED) | 3 | 2026-08-16 * |
| MEDIUM Findings (OPEN) | 16 | 2026-08-16 * |
| MEDIUM Findings (IMPROVED) | 1 | 2026-08-16 * |
| MEDIUM Findings (FIXED) | 4 | 2026-08-16 * |
| LOW Findings (OPEN) | 8 | 2026-08-16 * |

> \* 2026-08-16 校正:原表(各行合计仅 54)与 `findings.md` 实际状态漂移,已按 findings.md 全量重算(合计 61:OPEN 46 / IMPROVED 3 / PARTIAL 1 / FIXED 11)。其余章节保留为归档前的历史快照。

## Per-Persona Coverage

| Persona | Sessions | Scenarios Run | Findings |
|---------|----------|---------------|----------|
| analyst | 4 | 31 | 29 |
| developer | 3 | 17 | 20 |
| casual | 2 | 22 | 12 |

## Scenario Execution Heatmap

| Scenario | Times Executed | Last Result | Last Run |
|----------|---------------|-------------|----------|
| S001     | 3 | PASS (14/20 mention entity, dense noise 30%, cluster 20) | 2026-05-24 |
| S002     | 3 | FAIL (100% event_time=None for CATL, timeline unusable) | 2026-05-11 |
| S003     | 1 | FAIL (graph unavailable) | 2026-05-09 |
| S004     | 3 | FAIL (117 irrelevant dense results, no warning) | 2026-05-24 |
| S005     | 2 | PASS (event_type CN→EN mapping FIXED, 20/20 match) | 2026-05-24 |
| S006     | 3 | FIXED (BYD 0→64, all short names work) | 2026-05-20 |
| S007     | 3 | PASS (time_range filtering FIXED, correct subset behavior) | 2026-05-20 |
| S008     | 1 | PASS (graph adds 85 entities, 17 clusters; off mode clean) | 2026-05-11 |
| S009     | 3 | FAIL (comparative mode exists but 1:13 severe imbalance) | 2026-05-24 |
| S010     | 1 | PASS (all 5 intents have valid JSON schema) | 2026-05-11 |
| S011     | 1 | FAIL (top-k=0 inconsistent, negative top-k no validation, hops=5 hangs) | 2026-05-16 |
| S012     | 2 | IMPROVED (Defect #1/#2/#5/#9 FIXED, #3/#15 still present, new dense noise) | 2026-05-24 |
| S013     | 4 | IMPROVED (量化交易/供应链金融 now return results, 半导体 regression 45→4) | 2026-05-24 |
| S014     | 1 | PARTIAL (graph adds value, limited edges) | 2026-05-09 |
| S015     | 1 | PASS (deterministic results, identical KU order across runs) | 2026-05-16 |
| ad-hoc-iran | 1 | FAIL (COMPARATIVE_ANALYSIS 0 results, FTS5 limits) | 2026-05-09 |
| ad-hoc-chip | 1 | FAIL (海思 0/20 命中, time_range 未生效) | 2026-05-10 |
| ad-hoc-catl | 1 | PARTIAL (CATL alias OK, comparison improved 15:5, graph empty for relationship) | 2026-05-11 |
| ad-hoc-time | 1 | FAIL (time_range 2025 vs 2026-04 returns identical results) | 2026-05-16 |

## Known Defect Verification Status

| Defect | Description | Verified Present | Verified Fixed | Last Checked |
|--------|-------------|-----------------|----------------|--------------|
| #1     | Entity hard gate | YES (F20260509-008) | YES (F20260524-004, BYD 61 results, fallback modes work) | 2026-05-24 |
| #2     | Event type vocabulary | YES (F20260509-007, F20260509-011, F20260516-005) | YES (F20260524-002, 股价变动→stock_price_change 20/20) | 2026-05-24 |
| #3     | FTS Chinese tokenization | YES (F20260509-016, F20260509-020, F20260509-023, F20260520-004) | - | 2026-05-24 |
| #4     | Scoring calibration | YES (F20260509-020) | PARTIAL (entity_bonus=10.0, dense scores as primary) | 2026-05-24 |
| #5     | Time parsing fallback | YES (F20260510-002, F20260516-006) | YES (F20260524-004, 2025→6, 2026-04→55) | 2026-05-24 |
| #6     | Cluster no direct search | - | - | - |
| #7     | Two-path scoring inconsistency | - | - | - |
| #8     | Graph add-only | - | - | - |
| #9     | find_related primary only | YES (F20260509-019) | YES (F20260524-004, multi-entity clusters: 腾讯13+小米7) | 2026-05-24 |
| #10    | Cluster over-expansion | YES (F20260509-001, F20260509-013, F20260509-025) | YES (F20260524-001, 141→20 for 小米, 96→18 for CATL) | 2026-05-24 |
| #11    | No dedup | YES (F20260509-018, F20260511-002) | YES (F20260524-001, 超级科技日 8/10→0/20, 20/20 unique) | 2026-05-24 |
| #12    | 1-hop graph | YES (F20260509-019, F20260511-006) | REGRESSION (F20260524-007, graph nodes 192→0) | 2026-05-24 |
| #13    | Legacy dead code | YES (F20260509-009) | YES (F20260509-009) | 2026-05-09 |
| #14    | LIKE filter fragility | - | - | - |
| #15    | No intent-aware retrieval | YES (F20260509-021, F20260511-003) | PARTIAL (F20260524-004, RISK≠OVERVIEW but results about wrong entity) | 2026-05-24 |
| #16    | No relaxation cascade | - | YES (F20260524-004, bm25_fallback/dense_fallback/entity_id_lookup modes) | 2026-05-24 |
| #17    | Per-request client init | - | - | - |

## Retrieval Quality Scores

> 4 维评分趋势，每次会话后更新。分数 1-5，越高越好。

### Session Averages

| Session | Persona | Queries | Relevance | Info Density | Redundancy | Temporal | Overall |
|---------|---------|---------|-----------|-------------|------------|----------|---------|
| ut-analyst-20260509-101500 | analyst | 4 | 3 | 2 | 2 | 2 | 2.3 |
| ut-developer-20260509-154500 | developer | 6 | 3 | 2 | 2 | 2 | 2.3 |
| ut-analyst-20260509-170000 | analyst | 8 | 2.5 | 2 | 2.5 | 3 | 2.5 |
| ut-analyst-20260509-173000 | analyst | 11 | 2 | 1.5 | 3 | 1 | 1.9 |
| ut-casual-20260510-002317 | casual | 6 | 2.2 | 2.0 | 2.0 | 1.5 | 1.9 |
| ut-analyst-20260511-120618 | analyst | 8 | 2.8 | 2.8 | 1.4 | 1.0 | 2.0 |
| ut-developer-20260516-103000 | developer | 5 | 2.0 | 2.2 | 2.8 | 1.6 | 2.1 |
| ut-casual-20260520-143848 | casual | 6 | 3.3 | 2.7 | 3.5 | 2.8 | 3.1 |
| ut-developer-20260524-131436 | developer | 8 | 2.8 | 3.0 | 3.8 | 1.0 | 2.7 |

### Cumulative Averages

| Dimension | Score | Trend | Sample Size |
|-----------|-------|-------|-------------|
| Relevance | 2.7 | ↑ | 62 |
| Info Density | 2.6 | ↑ | 62 |
| Redundancy | 2.8 | ↑ | 62 |
| Temporal | 1.6 | → | 62 |
| **Overall** | 2.4 | ↑ | 62 |

### Dimension-Defect Correlation

| Dimension | Primary Defect | Secondary Defect |
|-----------|---------------|-----------------|
| Relevance | #4 (打分校准, PARTIAL) | dense noise (new), #3 (FTS5 中文分词, still present) |
| Info Density | KU 粒度 | event_time 100% None (小米) |
| Redundancy | #11 (无去重, FIXED) | #10 (Cluster 过度扩展, FIXED) |
| Temporal | event_time 缺失 | published_at 回退未实现 |
