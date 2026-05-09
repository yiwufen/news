# User Testing Quality Metrics

> 每次测试会话结束后更新。

---

## Overall Statistics

| Metric | Value | Last Updated |
|--------|-------|--------------|
| Total Sessions | 2 | 2026-05-09 |
| Total Scenarios Executed | 10 | 2026-05-09 |
| Total Findings | 13 | 2026-05-09 |
| CRITICAL Findings (OPEN) | 1 | 2026-05-09 |
| HIGH Findings (OPEN) | 3 | 2026-05-09 |
| MEDIUM Findings (OPEN) | 1 | 2026-05-09 |
| LOW Findings (OPEN) | 3 | 2026-05-09 |
| CRITICAL Findings (FIXED) | 1 | 2026-05-09 |
| HIGH Findings (FIXED) | 1 | 2026-05-09 |
| MEDIUM Findings (FIXED) | 3 | 2026-05-09 |

## Per-Persona Coverage

| Persona | Sessions | Scenarios Run | Findings |
|---------|----------|---------------|----------|
| analyst | 1 | 4 | 9 |
| developer | 1 | 6 | 4 |
| casual | 0 | 0 | 0 |

## Scenario Execution Heatmap

| Scenario | Times Executed | Last Result | Last Run |
|----------|---------------|-------------|----------|
| S001     | 1 | PASS (with findings) | 2026-05-09 |
| S002     | 1 | FAIL (insufficient coverage) | 2026-05-09 |
| S003     | 1 | FAIL (graph unavailable) | 2026-05-09 |
| S004     | 0 | - | - |
| S005     | 1 | FAIL (filter eliminates all) | 2026-05-09 |
| S006     | 0 | - | - |
| S007     | 0 | - | - |
| S008     | 0 | - | - |
| S009     | 1 | FAIL (single-entity bias) | 2026-05-09 |
| S010     | 0 | - | - |
| S011     | 0 | - | - |
| S012     | 0 | - | - |
| S013     | 0 | - | - |
| S014     | 0 | - | - |
| S015     | 0 | - | - |

## Known Defect Verification Status

| Defect | Description | Verified Present | Verified Fixed | Last Checked |
|--------|-------------|-----------------|----------------|--------------|
| #1     | Entity hard gate | YES (F20260509-008) | - | 2026-05-09 |
| #2     | Event type vocabulary | YES (F20260509-007, F20260509-011) | YES (F20260509-007) | 2026-05-09 |
| #3     | FTS Chinese tokenization | LIKELY (F20260509-004) | - | 2026-05-09 |
| #4     | Scoring calibration | - | - | - |
| #5     | Time parsing fallback | - | - | - |
| #6     | Cluster no direct search | - | - | - |
| #7     | Two-path scoring inconsistency | - | - | - |
| #8     | Graph add-only | - | - | - |
| #9     | find_related primary only | - | - | - |
| #10    | Cluster over-expansion | YES (F20260509-001, F20260509-013) | YES (F20260509-001) | 2026-05-09 |
| #11    | No dedup | - | - | - |
| #12    | 1-hop graph | YES (F20260509-006) | YES (F20260509-006) | 2026-05-09 |
| #13    | Legacy dead code | YES (F20260509-009) | YES (F20260509-009) | 2026-05-09 |
| #14    | LIKE filter fragility | - | - | - |
| #15    | No intent-aware retrieval | YES (F20260509-006, F20260509-010) | YES (F20260509-006) | 2026-05-09 |
| #16    | No relaxation cascade | LIKELY (F20260509-008) | - | 2026-05-09 |
| #17    | Per-request client init | - | - | - |
