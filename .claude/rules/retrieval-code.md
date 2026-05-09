# Retrieval Code Change Rules

修改以下文件前，必须先运行 `/review-findings` 查阅用户测试发现：

- `src/retrieval/` 下任何文件
- `src/orchestration/graph.py`
- `src/graph/` 下任何文件
- `src/cli.py`（search 命令相关）
- `src/knowledge_base.py`（FTS5 / 查询相关）

确认你的修改不会导致 findings.md 中 OPEN 状态的发现恶化。
