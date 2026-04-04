# 当前进度总览

这份文档用于快速回答 4 个问题：

1. 当前主线做到哪里了
2. 现在能运行什么
3. 现在能看到什么结果
4. 还差哪些关键能力

如与其他文档有冲突，以 [docs/SHARED_RULES.md](D:/value/news/docs/SHARED_RULES.md) 为准；详细待办以 [PROGRESS.md](D:/value/news/PROGRESS.md) 为准。

## 当前主线

当前项目主线已经切到知识检索底座：

`RawDocument -> KnowledgeUnit -> Entity / EventCluster -> 图谱 -> 检索`

对应两个正式入口：

- `run_continuous(graph_enabled=True)`：离线知识化建库
- `run_pipeline(raw_query=..., graph_enabled=True)`：统一知识检索入口

当前不再兼容旧的 `IntelligenceParticle / RiskReport` 消费主线。

## 当前完成情况

| 模块 | 状态 | 你现在能看到什么 |
|------|------|------------------|
| 原始新闻入库 | 已完成 | SQLite 中有 `news_articles` |
| `KnowledgeUnit` 抽取 | 主线可用 | 可看到 `knowledge_units` 表和抽取计数 |
| 实体归一 | 主线可用 | 可看到 `entities` 表和实体结果 |
| 事件归并 | 主线可用 | 可看到 `event_clusters` 表和事件簇结果 |
| 图谱同步 | 主线可用 | 可看到 graph sync 节点/边计数 |
| 检索入口 | 主线可用 | `run_pipeline()` 直接返回知识检索结果 |
| BM25 / 向量 / 融合排序 | 未完成 | 当前还是知识库直查与简单排序 |

## 现在可以直接运行的内容

### 1. 跑离线知识化

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.pipeline import run_continuous

result = run_continuous(graph_enabled=True)
print(result)
"
```

你会看到类似这些字段：

- `knowledge_units_extracted`
- `knowledge_units_saved`
- `entities_saved`
- `clusters_saved`
- `nodes_created`
- `edges_created`
- `errors`

对应实现：

- [src/pipeline/continuous.py](D:/value/news/src/pipeline/continuous.py)

### 2. 跑统一检索入口

```bash
uv run python -c "
from dotenv import load_dotenv
load_dotenv()
from src.orchestration import run_pipeline

result = run_pipeline(
    raw_query='查看小米集团过去一年做的事情',
    graph_enabled=True,
)
print(result)
"
```

你会看到类似这些字段：

- `query`
- `source`
- `graph`
- `knowledge_units`
- `entities`
- `event_clusters`
- `total_count`

对应实现：

- [src/orchestration/graph.py](D:/value/news/src/orchestration/graph.py)
- [src/retrieval/knowledge_search.py](D:/value/news/src/retrieval/knowledge_search.py)

注意：

- `run_pipeline()` 的意图解析当前依赖 LLM 配置
- 若未配置 `ANTHROPIC_API_KEY`，入口会直接失败，这符合当前 fail-fast 开发约束

## 现在能直接查看的数据结果

### 1. 查看库里有多少知识对象

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/news.db')
for table in ['knowledge_units', 'entities', 'event_clusters', 'knowledge_processing_log']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(table, count)
conn.close()
"
```

### 2. 查看最近处理状态

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/news.db')
rows = conn.execute(
    'SELECT doc_id, status, knowledge_units_count, entities_count, clusters_count, error_message '
    'FROM knowledge_processing_log ORDER BY processed_at DESC LIMIT 20'
).fetchall()
for row in rows:
    print(row)
conn.close()
"
```

### 3. 查看最近的知识单元

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/news.db')
rows = conn.execute(
    'SELECT ku_id, unit_type, summary, cluster_id FROM knowledge_units ORDER BY updated_at DESC LIMIT 20'
).fetchall()
for row in rows:
    print(row)
conn.close()
"
```

## 结果怎么看

如果你只是想判断“项目现在有没有跑起来”，看下面这几个信号就够了：

- `run_continuous()` 返回的 `knowledge_units_saved > 0`
- `knowledge_processing_log` 里出现 `success`
- `knowledge_units` / `entities` / `event_clusters` 表里有数据
- `run_pipeline()` 返回非空的 `knowledge_units` 或 `entities`
- `graph.edges` 有结果，或者离线结果里 `nodes_created / edges_created > 0`

## 当前还没完成的关键点

这些是下一阶段真正影响检索质量的能力：

- `KnowledgeUnit` 稀疏索引
- `KnowledgeUnit` 向量索引
- BM25 / 向量 / 融合排序
- 图谱作为正式检索产物参与统一召回
- 面向 skill 的稳定统一检索契约

## 推荐查看顺序

如果你是第一次接手当前状态，建议按这个顺序看：

1. [docs/STATUS_OVERVIEW.md](D:/value/news/docs/STATUS_OVERVIEW.md)
2. [docs/SHARED_RULES.md](D:/value/news/docs/SHARED_RULES.md)
3. [PROGRESS.md](D:/value/news/PROGRESS.md)
4. [src/pipeline/continuous.py](D:/value/news/src/pipeline/continuous.py)
5. [src/orchestration/graph.py](D:/value/news/src/orchestration/graph.py)
6. [src/retrieval/knowledge_search.py](D:/value/news/src/retrieval/knowledge_search.py)
