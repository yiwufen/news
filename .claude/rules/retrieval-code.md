# Retrieval Code Change Rules

修改以下文件前，必须先运行 `/review-findings` 查阅用户测试发现：

- `src/retrieval/` 下任何文件
- `src/orchestration/graph.py`
- `src/graph/` 下任何文件
- `src/cli.py`（search 命令相关）
- `src/knowledge_base.py`（FTS5 / 查询相关）
- `src/entities.py`（实体解析相关）
- `src/event_clustering.py`（归并策略相关）

确认你的修改不会导致 findings.md 中 OPEN 状态的发现恶化。

## 检索评估（Retrieval Eval）

修改上述文件后，**必须**运行检索评估报告，对比改动前后的指标变化：

```bash
uv run python scripts/eval_report.py --input eval/golden_dataset_v1.json
```

### 当前基线（2026-05-09，364 queries，规则预标注）

| 指标 | 基线值 |
|------|--------|
| Recall@5 | 29.4% |
| Recall@20 | 39.3% |
| MRR | 0.188 |
| NDCG@10 | 0.564 |

### 要求

- 改动前：记录当前指标
- 改动后：重跑 report，报告指标变化
- 如果 Recall@5 下降超过 2 个百分点，必须说明原因并确认是否可接受
- 关注各 query_type 的指标变化，不只用全局指标判断
