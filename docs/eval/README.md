# 检索质量评估 (Retrieval Evaluation)

可复现的检索质量评估体系。用固定的 eval set + LLM judge 标注 + 标准 IR 指标，
取代之前主观、不可比的人肉测试 (`docs/user-testing/`)。

## 为什么需要这套

`docs/user-testing/findings.md` 的评估有三个结构性问题：

1. **无 ground truth** — "20 条中 4 条相关"全凭主观，无标注一致性检验
2. **跨轮不可比** — 每轮测的查询不同、数据库在持续写入，"分数上升"无法归因
3. **归因混淆** — 把 ETL 质量 (event_time 缺失) 算进检索分

本套方案通过**固定 eval set + 冻结 DB 快照 + 自动化指标**解决这三点。

## 核心设计

| 维度 | 决策 |
|------|------|
| **ground truth** | LLM judge (glm-5.1) 标注，3 级分级 |
| **标注粒度** | relevant=2 / partial=1 / irrelevant=0 |
| **标注范围** | 每条查询检索 top-100 候选，全部标注（判定池） |
| **Recall 分母** | 判定池相关总数（TREC 池化近似），非 top-k 内相关数 |
| **DB 快照** | 复制 `data/news.db` → `docs/eval/eval_snapshot.db`，固定使用 |
| **eval set** | 30 条固定查询 (`queries-v1.json`)，显式携带 intent |
| **judge 模型** | `EVAL_JUDGE_MODEL` 环境变量，默认 `glm-5.1` |

## 指标定义

| 指标 | 含义 | 用途 |
|------|------|------|
| **nDCG@10** | graded gain (0/1/2)，位置折损，理想排序归一化 | **主指标**，衡量排序质量 |
| **Recall@5** | top-5 命中占判定池相关总数的比例 | 首屏召回 |
| **Recall@20** | top-20 命中占判定池相关总数的比例 | 召回完整性 |
| **MRR@10** | 第一个相关结果位置倒数 | 快速命中能力 |
| **Precision@5** | top-5 中相关比例 | 首屏质量 |
| **zero-hit rate** | top-k 排名返回 0 相关结果的查询比例 | 完全失败率 (越低越好) |

二值指标 (Recall/MRR/Precision) 中 grade≥1 计为命中。
所有指标按查询类别 (`single_entity_baseline` / `alias_resolution` /
`topic_no_entity` / `comparative` / `intent_contrast` / `parameterized`)
分组聚合，定位哪类查询最差。

### Recall 的池化判定 (TREC-style pooling)

Recall@k 的分母是「判定池相关总数」，不是「top-k 内的相关数」。
判定池 (judge pool) 由检索返回的前 `judge_pool_k`（默认 100）条候选组成，
judge 标注全部候选，池内 grade≥1 的总数即为所有 Recall@k 的共用分母。

这是标准 TREC 池化近似：避免了旧实现「top-k 命中数 / top-k 相关数」
导致的同义反复（分母与分子同源，Recall 趋近 1，无法反映真实召回）。
代价是每条查询需标注约 100 条（首次约 3000 次 LLM 调用，后续重跑因
judge 缓存按 `(query_id, ku_id, judge_model)` 增量，只标新增）。

### nDCG 的池化近似说明

nDCG@10 的理想排序上界 (IDCG) 由「判定池内的最优排序」决定，而非全库。
因此若某个高度相关的 KU 在 top-100 候选之外（检索阶段就漏召回），
nDCG 无法感知该损失。这是 pooled-IDCG 近似的固有局限——nDCG 衡量的是
「已召回候选的排序质量」，而非「召回是否完整」（后者由 Recall 指标负责）。

### judge 对过滤约束的处理

若查询携带 `time_range` 或 `event_types` 过滤，judge 会把不满足这些
硬约束的知识单元判为 irrelevant (0)，即使实体/主题匹配。这使得带过滤参数
的查询 (parameterized 类别) 的低分能正确归因到「过滤失效」，而非被
主题相关的假命中虚高。

## 评估流程

```
queries-v1.json (30 条固定查询)
  │
  ├─ make_query() → StructuredQuery (显式 intent)
  ├─ run_pipeline(db_path=eval_snapshot.db, top_k=judge_pool_k=100)  ← 冻结快照
  ├─ judge.label_query_hits() ← 标注全部 100 条候选，缓存增量
  └─ metrics.compute_query_metrics()
        │   ├─ Recall@k 分母 = 判定池相关总数 (grade≥1 across pool)
        │   └─ nDCG/MRR/Precision 在标准截断点评估
        ├─ results/<ts>_report.json  (完整明细)
        └─ results/<ts>_report.txt   (汇总表)
```

## 快速开始

```bash
# 1. 确保 .env 配置了 ANTHROPIC_API_KEY / ANTHROPIC_API_BASE_URL
# 2. (可选) 指定 judge 模型，默认 glm-5.1
#    export EVAL_JUDGE_MODEL=glm-5.1

# 3. 创建 DB 快照 (首次，从 data/news.db 复制)
uv run python docs/eval/scripts/snapshot.py

# 4. 跑评估 (3 条查询的冒烟测试)
uv run python docs/eval/scripts/run_eval.py --limit 3

# 5. 完整评估 (30 条)
uv run python docs/eval/scripts/run_eval.py
```

**常用参数**：

| 参数 | 作用 |
|------|------|
| `--limit N` | 只跑前 N 条查询 (冒烟测试) |
| `--refresh` | 忽略 judge 缓存，全部重新标注 |
| `--judge-pool-k 100` | 每条查询检索并标注多少候选 (Recall 分母池，默认 100) |
| `--db PATH` | 指定 DB 路径 (默认 eval_snapshot.db) |
| `--judge-model NAME` | 指定 judge 模型 |

## 可复现性保证

每次评估的报告记录：
- eval set 版本 (`v1`)
- judge 模型名
- 快照元数据：KU 总数、git commit、源 DB sha256、创建时间
- 每条查询的完整 ranked_ku_ids + grades

judge 标注缓存在 `golden_labels/v1_labels.json`，keyed by
`(query_id, ku_id, judge_model)`。重跑时只标注新增/变更的 KU，
断点续跑。换 judge 模型时旧标签保留，新模型重新标注。

## 文件结构

```
docs/eval/
├── README.md                      ← 本文件
├── queries-v1.json                ← 30 条固定查询
├── eval_snapshot.db               ← 冻结 DB 快照 (.gitignore)
├── snapshot_meta.json             ← 快照元数据 (.gitignore)
├── golden_labels/
│   └── v1_labels.json             ← judge 标注缓存 (版本化)
├── results/                       ← 历次评估报告 (.gitignore)
│   └── <ts>_report.json
└── scripts/
    ├── snapshot.py                ← 快照管理
    ├── judge.py                   ← LLM judge 标注
    ├── metrics.py                 ← 指标计算
    └── run_eval.py                ← 主流程
```

## 与旧评估的关系

| | 旧 (`docs/user-testing/`) | 新 (`docs/eval/`) |
|---|---|---|
| ground truth | 人工主观 | LLM judge (glm-5.1) |
| 指标 | 1-5 分打分 | nDCG/Recall/MRR (标准 IR) |
| 可复现 | 否 (查询/数据库都变) | 是 (固定 eval set + 冻结快照) |
| 归因 | 混淆 (检索+ETL+数据漂移) | 隔离 (纯检索质量) |
| 用途 | bug hunting 记录 | 质量回归基线 |

旧 findings 作为 bug 报告仍有价值，但不再作为质量度量基线。
