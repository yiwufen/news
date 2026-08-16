# Retrieval Code Change Rules

修改以下文件前，必须先运行 `$review-findings` 查阅用户测试发现：

- `src/retrieval/` 下任何文件
- `src/orchestration/graph.py`
- `src/graph/` 下任何文件
- `src/cli.py`（search 命令相关）
- `src/knowledge_base.py`（FTS5 / 查询相关）
- `src/entities.py`（实体解析相关）
- `src/event_merging.py`（归并策略相关）

确认你的修改不会导致 findings.md 中 OPEN 状态的发现恶化。

> 注：`docs/user-testing/findings.md` 属已归档体系（质量度量基线现为 `docs/eval/`），但其 OPEN 项仍是有效的 bug 线索，上述查阅要求继续适用。

## 检索评估（Retrieval Eval）

修改上述文件后，**必须**运行本地 EDD 回归门禁（用新代码 + 固定 fixture DB 重跑检索，
对比 `eval/baseline.json` 钉死的基线）：

```bash
# 1. 在 fixture DB 上重跑 golden 集，产出当前指标
uv run python scripts/eval_run.py \
    --fixture tests/fixtures/eval_snapshot.db \
    --golden eval/golden_dataset_v3.json \
    --output eval/run_latest.json

# 2. 门禁对比：超标非零退出
uv run python scripts/eval_guard.py --run eval/run_latest.json
```

> 注意：`eval_report.py` 只读冻结在 JSON 里的排名，无法检测检索代码回归；
> 真正的回归检测靠上面的 `eval_run.py` + `eval_guard.py`。
> `eval_report.py` 仅用于查看历史快照指标。

### 基线刷新流程

当 fixture DB 或 golden 集有意更新后，需要重置基线：

```bash
# 在真实库环境（远程）重生成 fixture
uv run python scripts/snapshot_eval_pair.py \
    --golden eval/golden_dataset_v3.json \
    --source-db data/news.db

# 本地首跑并写入新基线
uv run python scripts/eval_run.py --init-baseline
```

### 门禁阈值

- 全局 Recall@5 下降 > 2pp → FAIL
- 任一 query_type Recall@5 下降 > 5pp → FAIL
- fixture_db / golden_dataset sha256 漂移 → 硬失败（必须刷新 baseline）
- MRR 下降 > 0.03 → WARN（不阻断）

### ⚠ 基线语义与局限（重要）

本地 EDD 的 Recall@5/MRR **绝对值不代表真实召回水平**，只用于**回归检测**。

原因：fixture DB 是 golden 集涉及 KU 的子集（约 80 KU，远小于真实库），
查询候选池被裁剪，ground truth 几乎必然排第一 → 本地 Recall@5 趋近 100% 是假象。
真实召回水平需在**部署后**用远程全量库只读验证（`eval_generate.py` + `eval_report.py`）。

**EDD 的真正价值**：同一 fixture DB 上，代码改动后指标是否下降（防回归），
而非评估绝对召回质量。不要拿本地 Recall@5 当优化检索的目标值。

golden 集会随 KU id 体系变化而失效（如 v2 的 `em_` 前缀 → 现语义化命名），
`eval_report.py --skip-freshness` 之外，`eval_run.py` 首跑若 Recall 异常低，
先检查 golden 集 KU id 是否仍在库中（`snapshot_eval_pair.py` 会打印失配数）。

### v2 历史基线（已失效，仅存档）

> v2 的 KU id 体系（`em_` 前缀）已与当前库（语义化命名）失配，1162/1163 ground truth 失效，
> 以下数字不可复现。当前活基线以 v3 + `eval/baseline.json` 为准。

| 指标 | 基线值 |
|------|--------|
| Recall@5 | 71.7% |
| Recall@20 | 89.3% |
| MRR | 0.535 |
| NDCG@10 | 0.667 |

#### 按 query_type

| 类型 | 数量 | Recall@5 | MRR | NDCG@10 |
|------|------|----------|-----|---------|
| entity_event_type | 51 | 92.2% | 0.700 | 0.778 |
| multi_entity | 56 | 92.9% | 0.791 | 0.877 |
| entity_time | 41 | 70.7% | 0.545 | 0.683 |
| broad_topic | 72 | 55.6% | 0.383 | 0.532 |
| entity_only | 80 | 58.8% | 0.383 | 0.531 |

> 生成命令：`uv run python scripts/eval_generate.py --rule-based --output eval/golden_dataset_v2.json`
> 旧基线（v2, LLM 生成）因数据库重建导致 90% ground truth KU 失效，指标不可信。

### 要求

- 改动前：记录当前指标
- 改动后：重跑 report，报告指标变化
- 如果 Recall@5 下降超过 2 个百分点，必须说明原因并确认是否可接受
- 关注各 query_type 的指标变化，不只用全局指标判断

## 实体解析评估（Entity Resolution Eval）

修改 `src/entities.py` 中的合并逻辑（`_find_match`、`normalize_entity_name`、`resolve_units_with_cache`）后，**必须**运行实体解析评估：

```bash
uv run python scripts/eval_entity_resolution.py
```

### 当前基线（2026-05-16，2145 pairs，67 mentions，规则标注）

| 指标 | 基线值 |
|------|--------|
| Precision | 1.000 |
| Recall | 1.000 |
| F1 | 1.000 |
| False Positives | 0 |
| False Negatives | 0 |

> 结果保存在 `eval/entity_resolution_eval.json`。

### 评估维度

- **Precision（精度）**：不同实体未被误合并。覆盖子公司/相似名称场景（美的集团≠美的置业、小米≠小米金融、恒大健康≠恒大地产、蔚来≠蔚来汽车≠蔚来能源、中信证券≠中信建投）
- **Recall（召回）**：同一实体的不同表述被正确合并。覆盖跨语言别名（BYD→比亚迪、Tesla→特斯拉、IMF→国际货币基金组织、Pony Ma→马化腾）、类型不一致（腾讯 Person→腾讯控股 Company）、后缀变体（宁德时代股份有限公司→宁德时代）、复合后缀（阿里巴巴集团控股有限公司→阿里巴巴）、人名尊称（马化腾先生→马化腾）、跨语言新实体创建（IMF→国际货币基金组织）

### 要求

- Precision 不允许下降（误合并不可接受，保守策略底线）
- Recall 下降超过 0.1 必须说明原因
- 新增的 ground truth 用例应同时包含 precision 和 recall case
- 如果发现新的边界 case，补充到 `GROUND_TRUTH` 列表中
