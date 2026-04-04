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
- 当前进度总览：[`docs/STATUS_OVERVIEW.md`](docs/STATUS_OVERVIEW.md)
- 当前进度：[`PROGRESS.md`](PROGRESS.md)
- Codex 入口：[`AGENTS.md`](AGENTS.md)
- Claude Code 入口：[`CLAUDE.md`](CLAUDE.md)

如果多个文档表述不一致，以 `docs/SHARED_RULES.md` 为准。

## 当前状态

当前主线已经切到知识底座：`run_continuous()` 负责离线知识化建库，`run_pipeline()` 直接检索 `KnowledgeUnit` / `Entity` / `EventCluster`。旧的风险导向消费链路不再作为默认实现维护。

当前检索主线已包含：

- `KnowledgeUnit` FTS 稀疏索引
- `KnowledgeUnit` embedding 向量索引
- BM25 / 向量召回与融合排序
- 旧 SQLite 库的检索物化状态自愈：仓库打开时会自动回填缺失的 `entity_ids` 并重建缺失的 FTS 行，避免出现“图里有实体、知识库检索为空”的状态漂移

## 开发命令

```bash
uv sync
uv run pytest
uv run pyright .
```

说明：
- 仓库通过 `uv.toml` 将 `uv` 缓存固定到项目内的 `.uv-cache/`，避免依赖用户目录下的全局缓存初始化。

## 当前入口

### 持续运行模式

```bash
uv run python -c "
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path('.env'))
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=True)
print(result)
"
```

### 任务入口

```bash
uv run python -c "
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path('.env'))
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=True,
)
print(result)
"
```

说明：

- `run_continuous()` 是当前阶段的重点入口
- `run_pipeline()` 直接检索 `KnowledgeUnit` / `Entity` / `EventCluster`
- 图谱默认开启
- 若未配置 `ANTHROPIC_API_KEY`，`run_pipeline()` 的意图解析会按 fail-fast 约束直接失败
- 若未配置 embedding 凭据，`run_pipeline()` 会退化到 BM25-only 检索，而不会让默认知识库查询路径整体失败

## 协作约定

- 项目级规则统一维护在 `docs/SHARED_RULES.md`
- 完成功能后同步更新 `PROGRESS.md`
- 运行接口语义保持不变：`run_continuous()`、`run_pipeline()`
- 优先围绕知识底座重构，不再新增以风险报告为中心的项目级设计
