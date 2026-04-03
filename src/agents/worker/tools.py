"""
Worker Agent Tool Schema 定义

定义 LLM Tool Use 的输入输出 Schema。
"""

from typing import Any

from src.schemas import IntelligenceParticle

# === Tool Use Schema ===

EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "extract_intelligence_particle",
    "description": """从新闻文本中提取结构化情报微粒。

输出字段说明：
- metadata.source: 来源文件名或 URL
- metadata.event_time: 事件发生日期 (YYYY-MM-DD)
- metadata.reliability: 信息可靠度 (0-1)
- risk_signal.type: 事件类型 (DEBT_DEFAULT/EQUITY_PLEDGE/LEGAL_SUIT/REAL_CONTROL_CHANGE/RESTRUCTURING/POLICY_SANCTION)
- risk_signal.level: 风险等级 (CRITICAL/HIGH/MEDIUM/LOW)
- risk_signal.description: 风险描述 (10-500字)
- graph_updates.nodes: 涉及实体列表 [{id, label, type: COMPANY/PERSON/ASSET/FINANCIAL_PRODUCT}]
- graph_updates.edges: 关系列表 [{source, target, relation, properties}]
- traceability.source_doc_ids: 原始文档 ID 列表
- traceability.is_contradictory: 是否存在冲突情报
""",
    "input_schema": IntelligenceParticle.model_json_schema(),
}
