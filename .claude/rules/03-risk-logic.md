# 风险传导算法规则

## 1. 传导计算公式

```
Target_Risk = Σ(Source_Risk × Path_Weight × Time_Decay)
```

**参数说明：**
- `Source_Risk`: 源头风险分值 (0-1)
- `Path_Weight`: 路径传导系数 (见权重表)
- `Time_Decay`: 时间衰减系数 (见衰减表)

## 2. 时间衰减 (Time Decay)

| 时间范围 | 衰减系数 | 说明 |
|----------|----------|------|
| 3 个月内 | 1.0 | 全权重，当前风险 |
| 3-6 个月 | 0.7 | 高相关性，近期风险 |
| 6-12 个月 | 0.4 | 中等相关，趋势风险 |
| 1 年以上 | 0.1 | 低相关，历史背景 |

**实现示例：**
```python
def calculate_time_decay(event_date: date, reference_date: date) -> float:
    days_diff = (reference_date - event_date).days
    if days_diff <= 90:
        return 1.0
    elif days_diff <= 180:
        return 0.7
    elif days_diff <= 365:
        return 0.4
    else:
        return 0.1
```

## 3. 路径搜索深度

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 穿透深度 | 3 层 | 从目标实体向下搜索 3 层关系 |
| 最大路径数 | 50 | 限制返回路径数量，防止爆炸 |
| 最小风险阈值 | 0.3 | 低于此值的路径不纳入报告 |

## 4. 特殊风险模式

### 4.1 环形担保 (A → B, B → A)
- **风险等级**: CRITICAL
- **处理**: 自动标记，触发人工审核
- **说明**: 双向担保可能隐藏关联交易风险

### 4.2 链式担保 (A → B → C)
- **风险等级**: HIGH
- **处理**: 计算累积风险分值
- **说明**: 链条末端风险可能被放大

### 4.3 多对一担保 (A → C, B → C)
- **风险等级**: MEDIUM
- **处理**: 聚合计算总担保金额
- **说明**: 被担保方 C 的风险传导至所有担保方

## 5. 风险分值计算示例

```python
from dataclasses import dataclass
from datetime import date
from typing import List

@dataclass
class RiskPath:
    source_risk: float      # 源头风险分值
    path_weight: float      # 传导系数
    time_decay: float       # 时间衰减
    relation_chain: List[str]  # 关系链路

def calculate_target_risk(paths: List[RiskPath]) -> float:
    """计算目标实体的综合风险分值"""
    total_risk = sum(
        p.source_risk * p.path_weight * p.time_decay
        for p in paths
    )
    return min(total_risk, 1.0)  # 上限为 1.0

def classify_risk_level(score: float) -> str:
    """根据分值判定风险等级"""
    if score >= 0.8:
        return "CRITICAL"
    elif score >= 0.6:
        return "HIGH"
    elif score >= 0.4:
        return "MEDIUM"
    else:
        return "LOW"
```

## 6. Cypher 查询模板

### 6.1 3 层穿透查询
```cypher
MATCH path = (target:Company {name: $company_name})-[*1..3]-(related)
WHERE related:Company OR related:RiskEvent
RETURN path,
       reduce(risk = 0, n IN nodes(path) |
         risk + coalesce(n.risk_score, 0)) as cumulative_risk
ORDER BY cumulative_risk DESC
LIMIT 50
```

### 6.2 担保链路检测
```cypher
MATCH (a:Company)-[:GUARANTEES]->(b:Company)-[:GUARANTEES]->(c:Company)
RETURN a.name, b.name, c.name
```

### 6.3 环形担保检测
```cypher
MATCH (a:Company)-[:GUARANTEES]->(b:Company)-[:GUARANTEES]->(a)
RETURN DISTINCT a.name, b.name
```
