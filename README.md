# Financial Knowledge Retrieval Foundation

本项目当前定位为一个面向金融场景的知识检索底座，目标是把原始消息加工为可检索、可溯源、可组合的知识层，供后续 skill 驱动的分析 agent 执行通用金融任务。

它不是一个以“风险报告生成”为唯一目标的产品。风险分析、时间线、主题研究、关系扩展等都属于后续消费该底座的 skill。

## 核心方向

当前阶段重点是：

- 原始消息标准化
- `KnowledgeUnit` 抽取
- `EventCluster` 保守归并
- `Entity` 标准化
- 图谱更新
- 文本、语义、图谱多索引建库

第一版图谱是正式产物，采用 `Entity + EventCluster` 双核心建模；底层证据统一由 statement-level `KnowledgeUnit` 承载。

## 文档入口

- 项目共享规范真源：[`docs/SHARED_RULES.md`](docs/SHARED_RULES.md)
- 当前进度：[`PROGRESS.md`](PROGRESS.md)
- Codex 入口：[`AGENTS.md`](AGENTS.md)
- Claude Code 入口：[`CLAUDE.md`](CLAUDE.md)

如果多个文档表述不一致，以 `docs/SHARED_RULES.md` 为准。

## 当前状态

仓库里仍保留一部分旧的风险导向实现，例如 `IntelligenceParticle`、`RiskReport` 和部分风险图查询逻辑。它们属于迁移期遗留实现，不再代表项目目标架构。

当前研发重点应优先放在 `run_continuous()` 驱动的离线知识化建库，而不是继续扩展旧的风险分析消费链路。

## 开发命令

```bash
uv sync
uv run pytest
uv run pyright .
```

## 当前入口

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

### 任务入口

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

说明：

- `run_continuous()` 是当前阶段的重点入口
- `run_pipeline()` 在迁移期仍可保留，但不代表项目最终产品形态

## 协作约定

- 项目级规则统一维护在 `docs/SHARED_RULES.md`
- 完成功能后同步更新 `PROGRESS.md`
- 运行接口语义保持不变：`run_continuous()`、`run_pipeline()`
- 优先围绕知识底座重构，不再新增以风险报告为中心的项目级设计
