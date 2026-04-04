# News Collector

金融风险情报项目，围绕“新闻采集 -> 情报微粒提取 -> 图谱同步 -> 风险分析”构建双模式 Agent 流水线。

## 文档入口

- 项目共享规范真源：[`docs/SHARED_RULES.md`](docs/SHARED_RULES.md)
- Codex 入口：[`AGENTS.md`](AGENTS.md)
- Claude Code 入口：[`CLAUDE.md`](CLAUDE.md)
- 项目进度：[`PROGRESS.md`](PROGRESS.md)
- Claude 目录规则：[`.claude/rules/`](.claude/rules/)

## 开发命令

```bash
uv sync
uv run pytest
uv run pyright .
```

## 运行方式

### 持续运行模式

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=False)
print(result)
"
```

### 任务驱动模式

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=False,
)
print(result)
"
```

## 协作约定

- 项目级规则统一维护在 `docs/SHARED_RULES.md`
- `AGENTS.md` 和 `CLAUDE.md` 只做入口适配，不重复维护完整规范
- 完成功能后同步更新 `PROGRESS.md`
