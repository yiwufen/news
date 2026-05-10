"""
Canonical enumerations and type-normalization utilities.

The LLM knowledge extractor freely assigns ``unit_type`` and ``entity_type``
values.  This module defines the controlled vocabularies and normalization
functions that map raw LLM output to canonical types before persistence.
"""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# EventType / RelationType / EntityType (legacy risk-centric enums, kept for
# backward compatibility with graph and existing code)
# ---------------------------------------------------------------------------


class EventType(Enum):
    DEBT_DEFAULT = "债务违约"
    EQUITY_PLEDGE = "股权质押"
    LEGAL_SUIT = "重大诉讼"
    REAL_CONTROL_CHANGE = "实控人变动"
    RESTRUCTURING = "资产重组"
    POLICY_SANCTION = "政策制裁"


class RelationType(Enum):
    INVESTS = "股权投资"
    GUARANTEES = "担保"
    DEBTOR_OF = "债权债务"
    ACTUAL_CONTROL = "实际控制"
    OWNS = "资产所有权"
    ISSUES = "发行产品"


class EntityType(Enum):
    COMPANY = "公司实体"
    PERSON = "自然人"
    ASSET = "资产"
    FINANCIAL_PRODUCT = "金融产品"


class RiskLevel(Enum):
    CRITICAL = "立即预警"
    HIGH = "当日处理"
    MEDIUM = "周报汇总"
    LOW = "归档记录"


def classify_risk_score(score: float) -> RiskLevel:
    if score >= 0.8:
        return RiskLevel.CRITICAL
    elif score >= 0.6:
        return RiskLevel.HIGH
    elif score >= 0.4:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.LOW


# ---------------------------------------------------------------------------
# UnitType — canonical unit_type vocabulary
# ---------------------------------------------------------------------------


class UnitType(Enum):
    """Canonical unit_type values for KnowledgeUnit classification.

    The LLM is instructed to use these values.  Raw LLM output is
    normalized via ``normalize_unit_type()`` before persistence.
    """

    FINANCIAL_PERFORMANCE = "financial_performance"
    STOCK_PRICE_CHANGE = "stock_price_change"
    PRICE_CHANGE = "price_change"
    MARKET_ANALYSIS = "market_analysis"
    DIVIDEND = "dividend"
    IPO = "ipo"
    RESTRUCTURING = "restructuring"
    INVESTMENT = "investment"
    PRODUCT_LAUNCH = "product_launch"
    BUSINESS_STRATEGY = "business_strategy"
    COMPANY_ESTABLISHMENT = "company_establishment"
    EXECUTIVE_CHANGE = "executive_change"
    LEGAL_PROCEEDING = "legal_proceeding"
    REGULATORY_ACTION = "regulatory_action"
    POLICY_ANNOUNCEMENT = "policy_announcement"
    SANCTION = "sanction"
    DEBT_DEFAULT = "debt_default"
    EQUITY_PLEDGE = "equity_pledge"
    RISK_WARNING = "risk_warning"
    ECONOMIC_DATA = "economic_data"
    TRADE_DATA = "trade_data"
    SECTOR_PERFORMANCE = "sector_performance"
    DIPLOMATIC_EVENT = "diplomatic_event"
    MILITARY_ACTION = "military_action"
    POLITICAL_STATEMENT = "political_statement"
    ANNOUNCEMENT = "announcement"
    MEETING = "meeting"
    INDUSTRY_ANALYSIS = "industry_analysis"
    OTHER = "other"


# Canonical value set for fast membership testing
_CANONICAL_VALUES: set[str] = {t.value for t in UnitType}

# Alias mapping: lowercase raw string -> canonical UnitType
# Covers the top ~50 database variants + common Chinese/English synonyms.
_UNIT_TYPE_ALIASES: dict[str, UnitType] = {
    # --- financial_performance ---
    "financial_performance": UnitType.FINANCIAL_PERFORMANCE,
    "financial_report": UnitType.FINANCIAL_PERFORMANCE,
    "financial_result": UnitType.FINANCIAL_PERFORMANCE,
    "financial_statement": UnitType.FINANCIAL_PERFORMANCE,
    "financial_data": UnitType.FINANCIAL_PERFORMANCE,
    "财务业绩": UnitType.FINANCIAL_PERFORMANCE,
    "财务报告": UnitType.FINANCIAL_PERFORMANCE,
    "财报": UnitType.FINANCIAL_PERFORMANCE,
    "营收": UnitType.FINANCIAL_PERFORMANCE,
    "利润": UnitType.FINANCIAL_PERFORMANCE,
    "业绩预告": UnitType.FINANCIAL_PERFORMANCE,
    # --- stock_price_change ---
    "stock_price_change": UnitType.STOCK_PRICE_CHANGE,
    "stock_price_movement": UnitType.STOCK_PRICE_CHANGE,
    "stock_performance": UnitType.STOCK_PRICE_CHANGE,
    "stock_movement": UnitType.STOCK_PRICE_CHANGE,
    "股价变动": UnitType.STOCK_PRICE_CHANGE,
    "股价上涨": UnitType.STOCK_PRICE_CHANGE,
    "股价下跌": UnitType.STOCK_PRICE_CHANGE,
    "股价表现": UnitType.STOCK_PRICE_CHANGE,
    "股价": UnitType.STOCK_PRICE_CHANGE,
    "涨跌": UnitType.STOCK_PRICE_CHANGE,
    "股票表现": UnitType.STOCK_PRICE_CHANGE,
    # --- price_change ---
    "price_change": UnitType.PRICE_CHANGE,
    "price_movement": UnitType.PRICE_CHANGE,
    "price_increase": UnitType.PRICE_CHANGE,
    "price_decrease": UnitType.PRICE_CHANGE,
    "price_drop": UnitType.PRICE_CHANGE,
    "价格变动": UnitType.PRICE_CHANGE,
    "价格调整": UnitType.PRICE_CHANGE,
    "价格上涨": UnitType.PRICE_CHANGE,
    "价格下跌": UnitType.PRICE_CHANGE,
    # --- market_analysis ---
    "market_analysis": UnitType.MARKET_ANALYSIS,
    "market_performance": UnitType.MARKET_ANALYSIS,
    "market_trend": UnitType.MARKET_ANALYSIS,
    "market_movement": UnitType.MARKET_ANALYSIS,
    "market_data": UnitType.MARKET_ANALYSIS,
    "market_condition": UnitType.MARKET_ANALYSIS,
    "market_change": UnitType.MARKET_ANALYSIS,
    "市场分析": UnitType.MARKET_ANALYSIS,
    "市场表现": UnitType.MARKET_ANALYSIS,
    "市场趋势": UnitType.MARKET_ANALYSIS,
    "行情": UnitType.MARKET_ANALYSIS,
    # --- dividend ---
    "dividend": UnitType.DIVIDEND,
    "分红": UnitType.DIVIDEND,
    "派息": UnitType.DIVIDEND,
    # --- ipo ---
    "ipo": UnitType.IPO,
    "上市": UnitType.IPO,
    "上市申请": UnitType.IPO,
    # --- restructuring ---
    "restructuring": UnitType.RESTRUCTURING,
    "corporate_restructuring": UnitType.RESTRUCTURING,
    "asset_restructuring": UnitType.RESTRUCTURING,
    "资产重组": UnitType.RESTRUCTURING,
    "并购重组公告披露": UnitType.RESTRUCTURING,
    "重组性质": UnitType.RESTRUCTURING,
    "并购": UnitType.RESTRUCTURING,
    "重组": UnitType.RESTRUCTURING,
    # --- investment ---
    "investment": UnitType.INVESTMENT,
    "投资": UnitType.INVESTMENT,
    "融资": UnitType.INVESTMENT,
    "股权投资": UnitType.INVESTMENT,
    "战略投资": UnitType.INVESTMENT,
    # --- product_launch ---
    "product_launch": UnitType.PRODUCT_LAUNCH,
    "product_release": UnitType.PRODUCT_LAUNCH,
    "产品发布": UnitType.PRODUCT_LAUNCH,
    "产品研发": UnitType.PRODUCT_LAUNCH,
    "新品发布": UnitType.PRODUCT_LAUNCH,
    # --- business_strategy ---
    "business_strategy": UnitType.BUSINESS_STRATEGY,
    "business_scope": UnitType.BUSINESS_STRATEGY,
    "经营范围": UnitType.BUSINESS_STRATEGY,
    "企业战略": UnitType.BUSINESS_STRATEGY,
    "战略布局": UnitType.BUSINESS_STRATEGY,
    # --- company_establishment ---
    "company_establishment": UnitType.COMPANY_ESTABLISHMENT,
    "企业设立": UnitType.COMPANY_ESTABLISHMENT,
    "新设公司": UnitType.COMPANY_ESTABLISHMENT,
    # --- executive_change ---
    "executive_change": UnitType.EXECUTIVE_CHANGE,
    "control_change": UnitType.EXECUTIVE_CHANGE,
    "real_controller_change": UnitType.EXECUTIVE_CHANGE,
    "实控人变动": UnitType.EXECUTIVE_CHANGE,
    "高管变动": UnitType.EXECUTIVE_CHANGE,
    "人事变动": UnitType.EXECUTIVE_CHANGE,
    # --- legal_proceeding ---
    "legal_suit": UnitType.LEGAL_PROCEEDING,
    "legal_action": UnitType.LEGAL_PROCEEDING,
    "legal_proceeding": UnitType.LEGAL_PROCEEDING,
    "lawsuit": UnitType.LEGAL_PROCEEDING,
    "legal_decision": UnitType.LEGAL_PROCEEDING,
    "legal_ruling": UnitType.LEGAL_PROCEEDING,
    "legal_procedure": UnitType.LEGAL_PROCEEDING,
    "法律诉讼": UnitType.LEGAL_PROCEEDING,
    "诉讼纠纷": UnitType.LEGAL_PROCEEDING,
    "重大诉讼": UnitType.LEGAL_PROCEEDING,
    # --- regulatory_action ---
    "regulatory_action": UnitType.REGULATORY_ACTION,
    "监管处罚": UnitType.REGULATORY_ACTION,
    "行政处罚": UnitType.REGULATORY_ACTION,
    "合规调查": UnitType.REGULATORY_ACTION,
    # --- policy_announcement ---
    "policy": UnitType.POLICY_ANNOUNCEMENT,
    "policy_change": UnitType.POLICY_ANNOUNCEMENT,
    "policy_statement": UnitType.POLICY_ANNOUNCEMENT,
    "regulation": UnitType.POLICY_ANNOUNCEMENT,
    "政策发布": UnitType.POLICY_ANNOUNCEMENT,
    "政策声明": UnitType.POLICY_ANNOUNCEMENT,
    "政策变动": UnitType.POLICY_ANNOUNCEMENT,
    # --- sanction ---
    "sanction": UnitType.SANCTION,
    "政策制裁": UnitType.SANCTION,
    "制裁发布": UnitType.SANCTION,
    "制裁": UnitType.SANCTION,
    "禁运": UnitType.SANCTION,
    # --- debt_default ---
    "debt_default": UnitType.DEBT_DEFAULT,
    "debt_breach": UnitType.DEBT_DEFAULT,
    "债务违约": UnitType.DEBT_DEFAULT,
    "违约": UnitType.DEBT_DEFAULT,
    # --- equity_pledge ---
    "equity_pledge": UnitType.EQUITY_PLEDGE,
    "stock_pledge": UnitType.EQUITY_PLEDGE,
    "share_pledge": UnitType.EQUITY_PLEDGE,
    "股权质押": UnitType.EQUITY_PLEDGE,
    "质押": UnitType.EQUITY_PLEDGE,
    "解除质押": UnitType.EQUITY_PLEDGE,
    # --- risk_warning ---
    "warning": UnitType.RISK_WARNING,
    "风险提示": UnitType.RISK_WARNING,
    "警告": UnitType.RISK_WARNING,
    # --- economic_data ---
    "economic_data": UnitType.ECONOMIC_DATA,
    "economic_indicator": UnitType.ECONOMIC_DATA,
    "经济数据": UnitType.ECONOMIC_DATA,
    "经济指标": UnitType.ECONOMIC_DATA,
    # --- trade_data ---
    "trade_data": UnitType.TRADE_DATA,
    "贸易数据": UnitType.TRADE_DATA,
    # --- sector_performance ---
    "sector_performance": UnitType.SECTOR_PERFORMANCE,
    "板块表现": UnitType.SECTOR_PERFORMANCE,
    "板块分析": UnitType.SECTOR_PERFORMANCE,
    # --- diplomatic_event ---
    "diplomatic_event": UnitType.DIPLOMATIC_EVENT,
    "外交声明": UnitType.DIPLOMATIC_EVENT,
    "外交访问": UnitType.DIPLOMATIC_EVENT,
    # --- military_action ---
    "military_action": UnitType.MILITARY_ACTION,
    "军事行动": UnitType.MILITARY_ACTION,
    "军事部署": UnitType.MILITARY_ACTION,
    # --- political_statement ---
    "political_statement": UnitType.POLITICAL_STATEMENT,
    "政治声明": UnitType.POLITICAL_STATEMENT,
    # --- announcement ---
    "statement": UnitType.ANNOUNCEMENT,
    "announcement": UnitType.ANNOUNCEMENT,
    "声明": UnitType.ANNOUNCEMENT,
    "公告": UnitType.ANNOUNCEMENT,
    # --- meeting ---
    "meeting": UnitType.MEETING,
    "会议": UnitType.MEETING,
    # --- industry_analysis ---
    "industry_analysis": UnitType.INDUSTRY_ANALYSIS,
    "industry_trend": UnitType.INDUSTRY_ANALYSIS,
    "行业分析": UnitType.INDUSTRY_ANALYSIS,
    "行业趋势": UnitType.INDUSTRY_ANALYSIS,
    "analysis": UnitType.INDUSTRY_ANALYSIS,
}

# Keyword patterns for fuzzy matching (substring → UnitType)
_KEYWORD_PATTERNS: list[tuple[str, UnitType]] = [
    ("股价", UnitType.STOCK_PRICE_CHANGE),
    ("股票", UnitType.STOCK_PRICE_CHANGE),
    ("涨跌", UnitType.STOCK_PRICE_CHANGE),
    ("重组", UnitType.RESTRUCTURING),
    ("并购", UnitType.RESTRUCTURING),
    ("违约", UnitType.DEBT_DEFAULT),
    ("质押", UnitType.EQUITY_PLEDGE),
    ("诉讼", UnitType.LEGAL_PROCEEDING),
    ("制裁", UnitType.SANCTION),
    ("分红", UnitType.DIVIDEND),
    ("派息", UnitType.DIVIDEND),
    ("上市", UnitType.IPO),
    ("投资", UnitType.INVESTMENT),
    ("融资", UnitType.INVESTMENT),
    ("产品发布", UnitType.PRODUCT_LAUNCH),
    ("新品", UnitType.PRODUCT_LAUNCH),
    ("高管变动", UnitType.EXECUTIVE_CHANGE),
    ("人事变动", UnitType.EXECUTIVE_CHANGE),
    ("实控人", UnitType.EXECUTIVE_CHANGE),
    ("风险提示", UnitType.RISK_WARNING),
    ("监管", UnitType.REGULATORY_ACTION),
    ("处罚", UnitType.REGULATORY_ACTION),
    ("军事", UnitType.MILITARY_ACTION),
    ("外交", UnitType.DIPLOMATIC_EVENT),
    ("政策", UnitType.POLICY_ANNOUNCEMENT),
    ("经济", UnitType.ECONOMIC_DATA),
    ("行业", UnitType.INDUSTRY_ANALYSIS),
    ("板块", UnitType.SECTOR_PERFORMANCE),
]


def normalize_unit_type(raw_type: str) -> UnitType:
    """Map a raw LLM-extracted unit_type to the canonical UnitType.

    Lookup order:
    1. Exact match against canonical values
    2. Case-insensitive alias lookup
    3. Substring keyword matching
    4. Fallback to OTHER
    """
    if not raw_type or not raw_type.strip():
        return UnitType.OTHER

    stripped = raw_type.strip()

    # 1. Exact canonical match
    if stripped in _CANONICAL_VALUES:
        return UnitType(stripped)

    # 2. Alias lookup (case-insensitive)
    alias_hit = _UNIT_TYPE_ALIASES.get(stripped.lower())
    if alias_hit is not None:
        return alias_hit

    # 3. Keyword substring matching
    for keyword, unit_type in _KEYWORD_PATTERNS:
        if keyword in stripped:
            return unit_type

    return UnitType.OTHER


def get_unit_type_synonyms(canonical: UnitType) -> list[str]:
    """Return all known aliases for a canonical UnitType (for SQL IN filtering)."""
    synonyms: list[str] = [canonical.value]
    for alias, ut in _UNIT_TYPE_ALIASES.items():
        if ut == canonical:
            val = alias
            # Preserve original casing for known English values
            if not any("一" <= c <= "鿿" for c in val):
                # Find original-cased version
                for raw_alias in _UNIT_TYPE_ALIASES:
                    if raw_alias.lower() == alias:
                        val = raw_alias
                        break
            if val not in synonyms:
                synonyms.append(val)
    return synonyms
