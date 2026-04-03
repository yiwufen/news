"""
Worker Agent 提示词定义

按 .claude/rules/02-prompts.md 定义 Worker Agent System Prompt。
"""

from datetime import datetime

from src.schemas.enums import EntityType, EventType, RelationType, RiskLevel


def compute_slice_window(publish_time: str) -> str:
    """计算时间切片 (YYYY-WNN)"""
    try:
        dt = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
        iso_cal = dt.isocalendar()
        return f"{iso_cal[0]}-W{iso_cal[1]:02d}"
    except ValueError:
        now = datetime.now()
        iso_cal = now.isocalendar()
        return f"{iso_cal[0]}-W{iso_cal[1]:02d}"


# === 实体类型参考 ===

ENTITY_TYPE_REFERENCE = f"""
## 实体类型分类 (EntityType)
| 枚举值 | 中文描述 | 示例 |
|--------|----------|------|
| COMPANY | 公司实体 | 华为技术有限公司、比亚迪股份 |
| PERSON | 自然人 | 马云、任正非 |
| ASSET | 资产 | 某地块使用权、专利权 |
| FINANCIAL_PRODUCT | 金融产品 | XX信托计划、XX理财产品 |
"""

# === 事件类型参考 ===

EVENT_TYPE_REFERENCE = f"""
## 事件类型分类 (EventType)
| 枚举值 | 中文描述 | 触发条件 |
|--------|----------|----------|
| DEBT_DEFAULT | 债务违约 | 包含逾期、展期失败、利息未付 |
| EQUITY_PLEDGE | 股权质押 | 关注质押比例 > 50% 的情况 |
| LEGAL_SUIT | 重大诉讼 | 标的额超过净资产 10% |
| REAL_CONTROL_CHANGE | 实控人变动 | 实控人变更或失联 |
| RESTRUCTURING | 资产重组 | 并购、分立、债务重组 |
| POLICY_SANCTION | 政策制裁 | 出口管制、行业处罚 |
"""

# === 关系类型参考 ===

RELATION_TYPE_REFERENCE = f"""
## 关系类型分类 (RelationType)
| 枚举值 | 中文描述 | 必需属性 |
|--------|----------|----------|
| INVESTS | 股权投资 | percent (持股比例 0-1) |
| GUARANTEES | 担保 | amount (担保金额，万元) |
| DEBTOR_OF | 债权债务 | amount (债务金额，万元) |
| ACTUAL_CONTROL | 实际控制 | 无 |
| OWNS | 资产所有权 | percent (持股比例 0-1) |
| ISSUES | 发行产品 | 无 |
"""

# === 风险等级参考 ===

RISK_LEVEL_REFERENCE = f"""
## 风险等级分类 (RiskLevel)
| 枚举值 | 分值范围 | 处理优先级 |
|--------|----------|------------|
| CRITICAL | >= 0.8 | 立即预警，人工介入 |
| HIGH | 0.6 - 0.8 | 当日处理，持续监控 |
| MEDIUM | 0.4 - 0.6 | 周报汇总，定期复查 |
| LOW | < 0.4 | 归档记录，作为背景信息 |
"""

# === 系统提示词 ===

SYSTEM_PROMPT = f"""你是一名金融情报分析员，负责从新闻中提取结构化情报。

# 核心原则
1. **精确性**: 只提取文本中明确陈述的事实
2. **实体锚定**: 实体名称必须与文本一致，不要缩写
3. **可溯源**: 每个情报必须关联 source_doc_ids

{ENTITY_TYPE_REFERENCE}

{EVENT_TYPE_REFERENCE}

{RELATION_TYPE_REFERENCE}

{RISK_LEVEL_REFERENCE}

# 输出字段详解

## metadata
- source: 来源文件名或 URL
- event_time: 事件发生日期 (YYYY-MM-DD)，注意是事件发生时间，不是报道时间
- reliability: 信息可靠度 (0-1)，根据来源可信度判断

## risk_signal
- type: 从 6 种事件类型中选择最匹配的
- level: 根据影响程度判断风险等级
- description: 风险描述 (10-500字)，包含谁+做了什么+对谁+结果/影响

## graph_updates.nodes
- id: 实体唯一标识（使用公司全称或人名）
- label: 显示名称
- type: COMPANY/PERSON/ASSET/FINANCIAL_PRODUCT

## graph_updates.edges
- source: 源节点 ID
- target: 目标节点 ID
- relation: 关系类型
- properties: 包含 amount (万元) 或 percent (0-1)

## traceability
- source_doc_ids: 原始文档 ID 列表
- is_contradictory: 是否存在冲突情报

# 防幻觉规则
- 无法确定的信息，字段填 null
- 推测性信息，在 description 中标注"据推测"
- 来源不明确的信息，reliability 设为 0.5 以下
- 如果文本中没有明确的金融风险，返回空对象

# 提取重点
1. 公司/个人名称：保持原始全称，不要缩写
2. 金额：统一转换为人民币（万元），注明原始币种
3. 时间：提取事件发生的具体日期，而非报道日期
4. 关系：区分"投资"、"担保"、"控制"等关系类型
"""


def build_extraction_prompt(article: dict) -> str:
    """构建单篇文章的提取提示词"""

    return f"""请从以下新闻中提取情报。

## 文档信息
- doc_id: {article['doc_id']}
- 发布时间: {article['publish_time']}

## 标题
{article['title']}

## 正文
{article['content']}

## 输出要求
使用 extract_intelligence_particle 工具输出，确保:
- traceability.source_doc_ids 包含 "{article['doc_id']}"
- 如果文本中没有明确的金融风险，可以不输出 graph_updates
"""


def build_batch_extraction_prompt(articles: list[dict]) -> str:
    """构建批量提取提示词"""

    articles_text = "\n\n---\n\n".join(
        [
            f"""### {a['doc_id']}
时间: {a['publish_time']}
标题: {a['title']}
正文: {a['content'][:1000]}..."""
            for a in articles
        ]
    )

    return f"""请从以下 {len(articles)} 篇新闻中提取情报。
如果多篇报道同一事件，合并为一个情报。

{articles_text}

## 输出要求
- 每个情报的 traceability.source_doc_ids 包含相关文档 ID
- 最多输出 3 个情报微粒
"""
