"""Event type vocabulary mapping between user-facing terms and database unit_type values.

The knowledge extractor LLM freely assigns ``unit_type`` values, resulting in
thousands of distinct strings (English, Chinese, mixed case).  The EventType
enum in ``schemas.enums`` defines 6 canonical Chinese risk categories that
rarely match database values directly.  This module expands user-facing event
type terms to all known database variants so that SQL ``IN`` filtering can
actually match.
"""

from __future__ import annotations

# Each group is a set of synonyms that should match each other.
# A user-facing term in any group expands to ALL terms in that group.
_SYNONYM_GROUPS: list[list[str]] = [
    # --- EventType enum canonical terms + their DB variants ---
    # 债务违约 / DEBT_DEFAULT
    [
        "债务违约", "debt_default", "debt_breach", "Debt Sale",
        "违约", "credit_event",
    ],
    # 股权质押 / EQUITY_PLEDGE
    [
        "股权质押", "equity_pledge", "stock_pledge", "share_pledge",
        "股权质押风险", "解除质押", "stock_unpledge", "质押",
    ],
    # 重大诉讼 / LEGAL_SUIT
    [
        "重大诉讼", "legal_suit", "legal_action", "legal_proceeding",
        "lawsuit", "legal_decision", "legal_ruling", "legal_procedure",
        "法律诉讼", "诉讼纠纷", "诉讼时效到期事件",
        "legal_charge", "legal_filing", "legal_litigation",
        "legal_prosecution", "legal_violation", "Legal Case", "Legal Proceedings",
    ],
    # 实控人变动 / REAL_CONTROL_CHANGE
    [
        "实控人变动", "control_change", "real_controller_change",
        "ControlClaim",
    ],
    # 资产重组 / RESTRUCTURING
    [
        "资产重组", "restructuring", "corporate_restructuring",
        "asset_restructuring", "BusinessRestructuring",
        "并购重组公告披露", "重组性质",
    ],
    # 政策制裁 / POLICY_SANCTION
    [
        "政策制裁", "policy_sanction", "sanction",
        "制裁发布",
    ],
    # --- High-frequency broad categories ---
    # 价格变动 / price_change
    [
        "价格变动", "price_change", "price_movement", "price_increase",
        "价格调整", "price_decrease", "price_drop",
    ],
    # 股价
    [
        "股价变动", "股价上涨", "股价下跌", "股价表现",
        "stock_price_change", "stock_price_movement",
        "stock_performance", "stock_movement",
    ],
    # 财务
    [
        "财务业绩", "财务报告",
        "financial_performance", "financial_report",
        "financial_result", "financial_statement", "financial_data",
    ],
    # 声明 / statement
    [
        "声明", "statement", "Statement", "announcement",
    ],
    # 政策 / policy
    [
        "政策发布", "政策声明", "政策变动",
        "policy", "policy_change", "policy_statement", "regulation",
    ],
    # 产品发布 / product_launch
    [
        "产品发布", "product_launch", "product_release",
    ],
    # 市场
    [
        "市场分析", "市场表现", "市场趋势",
        "market_analysis", "market_performance", "market_trend",
        "market_movement", "market_data", "market_condition", "market_change",
    ],
    # 经济数据
    [
        "经济数据", "economic_indicator", "economic_data",
    ],
    # 外交/政治
    [
        "外交声明", "外交访问",
        "政治声明", "political_statement",
    ],
    # 军事
    [
        "军事行动", "military_action",
    ],
    # 投资
    [
        "投资", "investment",
    ],
    # 行业
    [
        "行业分析", "行业趋势", "板块表现",
        "industry_analysis", "industry_trend", "sector_performance",
    ],
    # 企业动态
    [
        "企业设立", "企业战略", "经营范围",
        "company_establishment", "business_strategy", "business_scope",
    ],
    # 会议
    [
        "会议", "meeting",
    ],
    # 警告/风险提示
    [
        "风险提示", "警告",
        "warning",
    ],
]

# Build lookup: any term -> all terms in its group
_LOOKUP: dict[str, list[str]] = {}
for group in _SYNONYM_GROUPS:
    for term in group:
        _LOOKUP[term.lower()] = group


def expand_event_types(user_types: list[str]) -> list[str]:
    """Expand user-facing event type terms to all known database variants.

    If a term is not in the vocabulary, it is passed through unchanged so that
    future database values still work without a mapping update.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for term in user_types:
        group = _LOOKUP.get(term.lower())
        if group:
            for synonym in group:
                key = synonym.lower()
                if key not in seen:
                    seen.add(key)
                    expanded.append(synonym)
        else:
            key = term.lower()
            if key not in seen:
                seen.add(key)
                expanded.append(term)
    return expanded
