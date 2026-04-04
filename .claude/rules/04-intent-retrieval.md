# 意图解析与检索层规范

## 1. 意图类型枚举 (Intent Types)

| 意图类型 | 说明 | 示例查询 |
|----------|------|----------|
| `ENTITY_TIMELINE` | 实体历史行为时间线 | "查看小米集团过去一年做的事情" |
| `RISK_ASSESSMENT` | 实体风险评估 | "分析某公司的债务风险" |
| `RELATIONSHIP_QUERY` | 实体关系路径查询 | "A公司和B公司有什么关联" |
| `COMPARATIVE_ANALYSIS` | 多实体对比分析 | "对比A和B两家公司的风险暴露" |
| `EVENT_IMPACT` | 事件影响分析 | "某事件对供应链有什么影响" |

---

## 2. 结构化查询输出 Schema

```python
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

class IntentType(Enum):
    ENTITY_TIMELINE = "ENTITY_TIMELINE"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    RELATIONSHIP_QUERY = "RELATIONSHIP_QUERY"
    COMPARATIVE_ANALYSIS = "COMPARATIVE_ANALYSIS"
    EVENT_IMPACT = "EVENT_IMPACT"

@dataclass
class TimeRange:
    start: date
    end: date

@dataclass
class QueryFilters:
    event_types: list[str] | None = None
    risk_levels: list[str] | None = None
    sources: list[str] | None = None
    min_credibility: float = 0.5

@dataclass
class StructuredQuery:
    """意图解析层的输出"""
    intent: IntentType
    entities: list[str]
    time_range: TimeRange | None
    filters: QueryFilters
    original_query: str
    confidence: float  # 解析置信度 0-1
```

---

## 3. 时间表达式解析规则

### 3.1 相对时间表达式

| 表达式 | 转换逻辑 |
|--------|----------|
| "过去一年" / "最近一年" | `start = today - 365d`, `end = today` |
| "过去三个月" / "近三个月" | `start = today - 90d`, `end = today` |
| "今年以来" | `start = 年初`, `end = today` |
| "上周" | `start = 上周一`, `end = 上周日` |
| "本月" | `start = 本月1日`, `end = today` |

### 3.2 绝对时间表达式

| 表达式 | 转换逻辑 |
|--------|----------|
| "2025年Q3" | `start = 2025-07-01`, `end = 2025-09-30` |
| "2025年上半年" | `start = 2025-01-01`, `end = 2025-06-30` |
| "2024财年" | `start = 2024-01-01`, `end = 2024-12-31` |
| "2025年3月" | `start = 2025-03-01`, `end = 2025-03-31` |

### 3.3 实现代码模板

```python
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

def parse_relative_time(expression: str, reference_date: date = None) -> TimeRange:
    """解析相对时间表达式"""
    ref = reference_date or date.today()
    expression = expression.strip().lower()
    
    if "过去一年" in expression or "最近一年" in expression:
        return TimeRange(
            start=ref - relativedelta(years=1),
            end=ref
        )
    elif "过去三个月" in expression or "近三个月" in expression:
        return TimeRange(
            start=ref - relativedelta(months=3),
            end=ref
        )
    elif "今年以来" in expression:
        return TimeRange(
            start=date(ref.year, 1, 1),
            end=ref
        )
    # ... 更多规则
    
    raise ValueError(f"无法解析时间表达式: {expression}")
```

---

## 4. 实体提取规则

### 4.1 实体识别策略

1. **精确匹配**：优先匹配数据库中已存在的公司名称
2. **别名映射**：维护常见公司别名词典
    * "小米" → "小米集团"
    * "阿里" → "阿里巴巴集团"
    * "腾讯" → "腾讯控股有限公司"
3. **后缀规范化**：移除常见后缀进行模糊匹配
    * "有限公司"、"股份公司"、"集团"、"控股"

### 4.2 实体扩展

对提取的实体进行同义词扩展，提升召回率：

```python
ENTITY_SYNONYMS = {
    "小米集团": ["小米", "Xiaomi", "小米科技", "小米公司"],
    "阿里巴巴": ["阿里", "Alibaba", "阿里集团", "阿里巴巴集团"],
    "腾讯": ["腾讯控股", "Tencent", "腾讯公司"],
}
```

---

## 5. 混合检索策略 (Hybrid Search)

### 5.1 双路召回

```python
@dataclass
class SearchResult:
    doc_id: str
    score: float
    source: str  # "bm25" | "vector" | "fusion"

def hybrid_search(query: StructuredQuery, top_k: int = 100) -> list[SearchResult]:
    """混合检索：BM25 + 向量检索"""
    
    # 1. BM25 字面检索 (精确匹配实体)
    bm25_results = bm25_search(
        query=query.entities,  # 实体名称作为关键词
        filters={"time_range": query.time_range},
        top_k=top_k
    )
    
    # 2. 向量语义检索 (捕获语义相关性)
    vector_results = vector_search(
        query=query.original_query,  # 原始查询作为语义输入
        filters={"time_range": query.time_range},
        top_k=top_k
    )
    
    # 3. RRF 融合
    return rrf_fusion(bm25_results, vector_results, k=60)
```

### 5.2 RRF (Reciprocal Rank Fusion) 算法

```
RRF_score(d) = Σ 1 / (k + rank(d))
```

其中 `k` 通常设为 60。

```python
def rrf_fusion(
    bm25_results: list[SearchResult],
    vector_results: list[SearchResult],
    k: int = 60
) -> list[SearchResult]:
    """倒数排名融合"""
    scores: dict[str, float] = {}
    
    # BM25 路径
    for rank, result in enumerate(bm25_results, 1):
        scores[result.doc_id] = scores.get(result.doc_id, 0) + 1 / (k + rank)
    
    # 向量路径
    for rank, result in enumerate(vector_results, 1):
        scores[result.doc_id] = scores.get(result.doc_id, 0) + 1 / (k + rank)
    
    # 排序输出
    return sorted(
        [SearchResult(doc_id=doc_id, score=score, source="fusion") 
         for doc_id, score in scores.items()],
        key=lambda x: x.score,
        reverse=True
    )
```

---

## 6. 元数据过滤 (Metadata Filtering)

### 6.1 过滤条件

| 字段 | 类型 | 说明 |
|------|------|------|
| `time_range` | TimeRange | 文章发布时间范围 |
| `credibility_tier` | int (1-3) | 来源可信度等级 |
| `category` | str | 文章分类 |
| `source_name` | str | 来源名称 |

### 6.2 SQL 过滤模板

```sql
SELECT * FROM news_articles
WHERE publish_time BETWEEN :start AND :end
  AND credibility_tier <= :min_tier
  AND category IN (:categories)
ORDER BY publish_time DESC
LIMIT :limit
```

---

## 7. 检索层输入输出契约

### 输入

```python
@dataclass
class RetrievalRequest:
    structured_query: StructuredQuery
    top_k: int = 100
    min_score: float = 0.3  # 最低相关性分数
```

### 输出

```python
@dataclass
class RetrievalResult:
    articles: list[dict]  # 候选文章列表
    total_count: int      # 命中总数
    bm25_count: int       # BM25 召回数
    vector_count: int     # 向量召回数
    fusion_stats: dict    # 融合统计
```

---

## 8. 开发检查清单

### 8.1 意图解析层

- [ ] 实现 `IntentClassifier` 意图分类器
- [ ] 实现 `EntityExtractor` 实体提取器
- [ ] 实现 `TimeRangeParser` 时间解析器
- [ ] 创建 `StructuredQuery` 数据模型
- [ ] 编写单元测试覆盖各种查询模式

### 8.2 检索层

- [ ] 集成 BM25 检索引擎 (如 `rank_bm25` 或 Elasticsearch)
- [ ] 集成向量检索引擎 (如 Qdrant 或 Milvus)
- [ ] 实现 RRF 融合算法
- [ ] 实现元数据过滤
- [ ] 建立实体别名词典
- [ ] 性能基准测试 (召回率/准确率)

---

## 9. 示例：完整处理流程

```
用户输入: "查看小米集团过去一年做的事情"
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 意图解析层                               │
│                                         │
│ 输出: StructuredQuery(                  │
│   intent = ENTITY_TIMELINE              │
│   entities = ["小米集团"]                │
│   time_range = TimeRange(               │
│     start = 2025-04-03,                 │
│     end = 2026-04-03                    │
│   )                                     │
│ )                                       │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ 检索层                                   │
│                                         │
│ BM25: "小米集团" → 45 篇                 │
│ Vector: "小米集团 过去一年 做的事情" → 38 篇 │
│ RRF 融合 → 62 篇 (去重后)                │
│ 元数据过滤 → 58 篇                       │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│ Worker Agent (并行处理)                  │
│                                         │
│ 时间切片: 2025-Q2, 2025-Q3, ...         │
│ 输出: 15 个情报微粒                       │
└─────────────────────────────────────────┘
                    │
                    ▼
               后续流程...
```
