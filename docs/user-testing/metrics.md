# User Testing Quality Metrics

> 每次测试会话结束后更新。

---

## Overall Statistics

| Metric | Value | Last Updated |
|--------|-------|--------------|
| Total Sessions | 6 | 2026-05-11 |
| Total Scenarios Executed | 54 | 2026-05-11 |
| Total Findings | 40 | 2026-05-11 |
| CRITICAL Findings (OPEN) | 4 | 2026-05-10 |
| CRITICAL Findings (PARTIAL) | 1 | 2026-05-09 |
| HIGH Findings (OPEN) | 11 | 2026-05-11 |
| HIGH Findings (IMPROVED) | 1 | 2026-05-09 |
| MEDIUM Findings (OPEN) | 7 | 2026-05-11 |
| LOW Findings (OPEN) | 6 | 2026-05-10 |
| CRITICAL Findings (FIXED) | 2 | 2026-05-09 |
| HIGH Findings (FIXED) | 3 | 2026-05-09 |
| MEDIUM Findings (FIXED) | 4 | 2026-05-09 |

## Per-Persona Coverage

| Persona | Sessions | Scenarios Run | Findings |
|---------|----------|---------------|----------|
| analyst | 4 | 31 | 29 |
| developer | 1 | 6 | 4 |
| casual | 1 | 17 | 7 |

## Scenario Execution Heatmap

| Scenario | Times Executed | Last Result | Last Run |
|----------|---------------|-------------|----------|
| S001     | 1 | PASS (with findings) | 2026-05-09 |
| S002     | 3 | FAIL (100% event_time=None for CATL, timeline unusable) | 2026-05-11 |
| S003     | 1 | FAIL (graph unavailable) | 2026-05-09 |
| S004     | 2 | PASS (structured warning added) | 2026-05-09 |
| S005     | 1 | FAIL (filter eliminates all) | 2026-05-09 |
| S006     | 2 | FIXED (EN aliases now resolve, BYD→19 results) | 2026-05-09 |
| S007     | 2 | PARTIAL (total_count changes but KU unaffected due to event_time=None) | 2026-05-11 |
| S008     | 1 | PASS (graph adds 85 entities, 17 clusters; off mode clean) | 2026-05-11 |
| S009     | 2 | FIXED (both entities represented: 7+8) | 2026-05-09 |
| S010     | 1 | PASS (all 5 intents have valid JSON schema) | 2026-05-11 |
| S011     | 0 | - | - |
| S012     | 0 | - | - |
| S013     | 2 | PARTIAL (BM25 fallback active, FTS5 still limits recall) | 2026-05-09 |
| S014     | 1 | PARTIAL (graph adds value, limited edges) | 2026-05-09 |
| S015     | 0 | - | - |
| ad-hoc-iran | 1 | FAIL (COMPARATIVE_ANALYSIS 0 results, FTS5 limits) | 2026-05-09 |
| ad-hoc-chip | 1 | FAIL (海思 0/20 命中, time_range 未生效) | 2026-05-10 |
| ad-hoc-catl | 1 | PARTIAL (CATL alias OK, comparison improved 15:5, graph empty for relationship) | 2026-05-11 |

## Known Defect Verification Status

| Defect | Description | Verified Present | Verified Fixed | Last Checked |
|--------|-------------|-----------------|----------------|--------------|
| #1     | Entity hard gate | YES (F20260509-008) | YES (F20260509-015, F20260509-016, F20260509-020) | 2026-05-09 |
| #2     | Event type vocabulary | YES (F20260509-007, F20260509-011, F20260511-007) | PARTIAL (F20260509-007) | 2026-05-11 |
| #3     | FTS Chinese tokenization | YES (F20260509-016, F20260509-020, F20260509-023) | - | 2026-05-09 |
| #4     | Scoring calibration | YES (F20260509-020) | - | 2026-05-09 |
| #5     | Time parsing fallback | YES (F20260510-002, F20260511-004) | - | 2026-05-11 |
| #6     | Cluster no direct search | - | - | - |
| #7     | Two-path scoring inconsistency | - | - | - |
| #8     | Graph add-only | - | - | - |
| #9     | find_related primary only | - | - | - |
| #10    | Cluster over-expansion | YES (F20260509-001, F20260509-013, F20260509-025) | YES (F20260509-001) | 2026-05-09 |
| #11    | No dedup | YES (F20260509-018, F20260511-002) | - | 2026-05-11 |
| #12    | 1-hop graph | YES (F20260509-019, F20260511-006) | PARTIAL (F20260509-006) | 2026-05-11 |
| #13    | Legacy dead code | YES (F20260509-009) | YES (F20260509-009) | 2026-05-09 |
| #14    | LIKE filter fragility | - | - | - |
| #15    | No intent-aware retrieval | YES (F20260509-021, F20260511-003) | PARTIAL (F20260509-006) | 2026-05-11 |
| #16    | No relaxation cascade | - | YES (F20260509-015, F20260509-016) | 2026-05-09 |
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

### Cumulative Averages

| Dimension | Score | Trend | Sample Size |
|-----------|-------|-------|-------------|
| Relevance | 2.6 | → | 43 |
| Info Density | 2.1 | → | 43 |
| Redundancy | 2.1 | ↓ | 43 |
| Temporal | 1.5 | ↓ | 43 |
| **Overall** | 2.1 | → | 43 |

### Dimension-Defect Correlation

| Dimension | Primary Defect | Secondary Defect |
|-----------|---------------|-----------------|
| Relevance | #4 (打分校准) | #1 (实体硬门, FIXED), #3 (FTS5 中文分词) |
| Info Density | KU 粒度 | #3 (FTS 中文分词) |
| Redundancy | #11 (无去重) | #10 (Cluster 过度扩展) |
| Temporal | #5 (时间解析回退) | event_time 缺失率 54%+ (CATL 100%) |
