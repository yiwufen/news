"""
Canonical enumerations and type-normalization utilities.

The LLM knowledge extractor freely assigns ``unit_type`` and ``entity_type``
values.  This module defines the controlled vocabularies and normalization
functions that map raw LLM output to canonical types before persistence.
"""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# UnitType — canonical unit_type vocabulary
# ---------------------------------------------------------------------------


class UnitType(Enum):
    """Canonical unit_type values for KnowledgeUnit classification.

    Closed set of 32 financial-event types (financial + financial-impact),
    plus ``non_financial`` as the out-of-scope exit. The legacy ``announcement``
    and ``other`` bucket types have been removed — see
    ``docs/graph_edge_design.md`` §3 for the rationale and per-type
    disambiguation priorities.

    The LLM is instructed to use these values.  Raw LLM output is
    normalized via ``normalize_unit_type()`` before persistence.
    """

    # --- 公司资本类 ---
    FINANCIAL_PERFORMANCE = "financial_performance"
    RESTRUCTURING = "restructuring"
    IPO = "ipo"
    SHAREHOLDING_CHANGE = "shareholding_change"
    EQUITY_PLEDGE = "equity_pledge"
    DIVIDEND = "dividend"
    COMPANY_ESTABLISHMENT = "company_establishment"
    INVESTMENT = "investment"
    # --- 公司经营类 ---
    PRODUCT_LAUNCH = "product_launch"
    BUSINESS_STRATEGY = "business_strategy"
    EXECUTIVE_CHANGE = "executive_change"
    # --- 公司风险类 ---
    DEBT_DEFAULT = "debt_default"
    LEGAL_PROCEEDING = "legal_proceeding"
    RISK_WARNING = "risk_warning"
    # --- 市场分析类 ---
    STOCK_PRICE_CHANGE = "stock_price_change"
    PRICE_CHANGE = "price_change"
    SECTOR_PERFORMANCE = "sector_performance"
    MARKET_ANALYSIS = "market_analysis"
    INDUSTRY_ANALYSIS = "industry_analysis"
    RATING_CHANGE = "rating_change"
    # --- 监管类 ---
    REGULATORY_ACTION = "regulatory_action"
    SANCTION = "sanction"
    POLICY_ANNOUNCEMENT = "policy_announcement"
    # --- 宏观类 ---
    ECONOMIC_DATA = "economic_data"
    TRADE_DATA = "trade_data"
    # --- 金融影响因素类 ---
    DIPLOMATIC_EVENT = "diplomatic_event"
    MILITARY_ACTION = "military_action"
    POLITICAL_STATEMENT = "political_statement"
    # --- 跨主体关系类 ---
    STRATEGIC_COOPERATION = "strategic_cooperation"
    # --- 信息披露与会议类 ---
    DISCLOSURE = "disclosure"
    MEETING = "meeting"
    # --- 边界外（明确非金融，非垃圾桶）---
    NON_FINANCIAL = "non_financial"


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
    # --- investment（不含控股性并购→restructuring；不含配股减持→shareholding_change）---
    "investment": UnitType.INVESTMENT,
    "投资": UnitType.INVESTMENT,
    "融资": UnitType.INVESTMENT,
    "股权投资": UnitType.INVESTMENT,
    "战略投资": UnitType.INVESTMENT,
    # --- shareholding_change（股东增/减持、大宗交易、配售，非控制权变动）---
    "shareholding_change": UnitType.SHAREHOLDING_CHANGE,
    "减持": UnitType.SHAREHOLDING_CHANGE,
    "增持": UnitType.SHAREHOLDING_CHANGE,
    "股东减持": UnitType.SHAREHOLDING_CHANGE,
    "股东增持": UnitType.SHAREHOLDING_CHANGE,
    "大宗交易": UnitType.SHAREHOLDING_CHANGE,
    "股份配售": UnitType.SHAREHOLDING_CHANGE,
    "配售": UnitType.SHAREHOLDING_CHANGE,
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
    # --- disclosure（原 announcement 重定向；上市公司就特定事项的正式信息披露）---
    "disclosure": UnitType.DISCLOSURE,
    "statement": UnitType.DISCLOSURE,
    "announcement": UnitType.DISCLOSURE,
    "声明": UnitType.DISCLOSURE,
    "公告": UnitType.DISCLOSURE,
    "澄清": UnitType.DISCLOSURE,
    "回应": UnitType.DISCLOSURE,
    "停牌": UnitType.DISCLOSURE,
    "复牌": UnitType.DISCLOSURE,
    "减持计划": UnitType.DISCLOSURE,
    # --- meeting ---
    "meeting": UnitType.MEETING,
    "会议": UnitType.MEETING,
    # --- industry_analysis ---
    "industry_analysis": UnitType.INDUSTRY_ANALYSIS,
    "industry_trend": UnitType.INDUSTRY_ANALYSIS,
    "行业分析": UnitType.INDUSTRY_ANALYSIS,
    "行业趋势": UnitType.INDUSTRY_ANALYSIS,
    "analysis": UnitType.INDUSTRY_ANALYSIS,
    # --- rating_change（机构评级/目标价/盈利预测的调整动作）---
    "rating_change": UnitType.RATING_CHANGE,
    "评级调整": UnitType.RATING_CHANGE,
    "目标价": UnitType.RATING_CHANGE,
    "上调评级": UnitType.RATING_CHANGE,
    "下调评级": UnitType.RATING_CHANGE,
    "维持评级": UnitType.RATING_CHANGE,
    "首次覆盖": UnitType.RATING_CHANGE,
    # --- strategic_cooperation（非投资性战略合作/签署协议）---
    "strategic_cooperation": UnitType.STRATEGIC_COOPERATION,
    "战略合作": UnitType.STRATEGIC_COOPERATION,
    "签署协议": UnitType.STRATEGIC_COOPERATION,
    "达成合作": UnitType.STRATEGIC_COOPERATION,
    "签约": UnitType.STRATEGIC_COOPERATION,
    # --- non_financial（明确非金融，非垃圾桶）---
    "non_financial": UnitType.NON_FINANCIAL,
}

# Keyword patterns for fuzzy matching (substring → UnitType)
_KEYWORD_PATTERNS: list[tuple[str, UnitType]] = [
    ("股价", UnitType.STOCK_PRICE_CHANGE),
    ("股票", UnitType.STOCK_PRICE_CHANGE),
    ("涨跌", UnitType.STOCK_PRICE_CHANGE),
    ("重组", UnitType.RESTRUCTURING),
    ("并购", UnitType.RESTRUCTURING),
    # shareholding_change 必须排在 investment 之前：减持/增持/配售含"持"易被误匹配
    ("减持", UnitType.SHAREHOLDING_CHANGE),
    ("增持", UnitType.SHAREHOLDING_CHANGE),
    ("大宗交易", UnitType.SHAREHOLDING_CHANGE),
    ("配售", UnitType.SHAREHOLDING_CHANGE),
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
    ("评级", UnitType.RATING_CHANGE),
    ("目标价", UnitType.RATING_CHANGE),
    ("战略合作", UnitType.STRATEGIC_COOPERATION),
    ("签署协议", UnitType.STRATEGIC_COOPERATION),
    ("签约", UnitType.STRATEGIC_COOPERATION),
    ("澄清", UnitType.DISCLOSURE),
    ("停牌", UnitType.DISCLOSURE),
    ("军事", UnitType.MILITARY_ACTION),
    ("外交", UnitType.DIPLOMATIC_EVENT),
    ("政策", UnitType.POLICY_ANNOUNCEMENT),
    ("经济", UnitType.ECONOMIC_DATA),
    ("行业", UnitType.INDUSTRY_ANALYSIS),
    ("板块", UnitType.SECTOR_PERFORMANCE),
]


def is_known_unit_type(raw_type: str) -> bool:
    """Return True iff ``raw_type`` resolves to a *real* canonical value.

    Unlike ``normalize_unit_type`` (which falls back to ``disclosure`` for
    anything unrecognised), this never reports a fallback as a match.  Use it
    when the caller must distinguish "genuinely recognised" from "defaulted".
    """
    if not raw_type or not raw_type.strip():
        return False
    stripped = raw_type.strip()
    if stripped in _CANONICAL_VALUES:
        return True
    if stripped.lower() in _UNIT_TYPE_ALIASES:
        return True
    return any(keyword in stripped for keyword, _ in _KEYWORD_PATTERNS)


def normalize_unit_type(raw_type: str) -> UnitType:
    """Map a raw LLM-extracted unit_type to the canonical UnitType.

    Lookup order:
    1. Exact match against canonical values
    2. Case-insensitive alias lookup
    3. Substring keyword matching
    4. Fallback to DISCLOSURE

    The legacy ``other`` bucket type has been removed; an unrecognised value
    is treated as an unspecified disclosure (the safest non-committal
    financial-event type) rather than silently dropped into a catch-all.
    See ``docs/graph_edge_design.md`` §3 for the rationale.
    """
    if not raw_type or not raw_type.strip():
        return UnitType.DISCLOSURE

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

    return UnitType.DISCLOSURE


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


# ---------------------------------------------------------------------------
# Legacy reclassification — map old 29-class canonicals to the new 32-class set
# ---------------------------------------------------------------------------

# Legacy values that were valid canonicals in the old taxonomy but no longer
# exist. They cannot be mapped deterministically by rules alone — their
# content must be re-read to pick the right new type.
LEGACY_BUCKET_TYPES: frozenset[str] = frozenset({"announcement", "other"})

# investment is kept as a canonical but pressure-testing showed ~50% of old
# investment KUs were mis-classified (配股→shareholding_change, 研报→rating_change,
# 设合伙企业→company_establishment). Rule-based mapping cannot tell these apart,
# so the reclassification script re-reads investment KUs via LLM as well.
LEGACY_NEEDS_RELABEL: frozenset[str] = frozenset({"announcement", "other", "investment"})


def reclassify_legacy_unit_type(old: str) -> tuple[UnitType, bool]:
    """Map an old-taxonomy canonical ``unit_type`` to the new closed set.

    Returns ``(new_type, needs_relabel)``:

    * ``needs_relabel=False`` — the rule mapping is certain; ``new_type`` is
      the final value. Covers the 27 types that survived unchanged.
    * ``needs_relabel=True`` — the old value is a removed bucket
      (``announcement``/``other``) or a noisy type (``investment``); the
      returned ``new_type`` is only a *placeholder* (``disclosure``) and the
      caller MUST re-read the KU content (via LLM) to assign the real type.

    Unknown inputs (not a legacy canonical) are treated as certain →
    ``disclosure``, since ``normalize_unit_type`` already handles them.
    """
    if old in LEGACY_NEEDS_RELABEL:
        return UnitType.DISCLOSURE, True
    # Surviving canonical — normalise to guard against case drift, then return
    # as-is. Anything unrecognised also lands on disclosure (certain).
    return normalize_unit_type(old), False


# ---------------------------------------------------------------------------
# Edge attribute derivation — role / scope / nature for INVOLVED_IN edges
# ---------------------------------------------------------------------------

# Entity types that count as "corporate" (a company's own affairs). Everything
# else (Organization / Person / None / unknown) is "environment" — external to
# the company scope. See docs/graph_edge_design.md §2.1.
_CORPORATE_ENTITY_TYPES: frozenset[str] = frozenset({"Company", "Product"})


def derive_edge_scope(entity_type: str | None) -> str:
    """Classify an INVOLVED_IN edge's scope as ``corporate`` or ``environment``.

    A pure mechanical mapping from the participating entity's type — no content
    reading. Company/Product → corporate; Organization/Person/None/unknown →
    environment. This is the "whose affair is it?" coarse filter used for
    multi-hop pruning.
    """
    if entity_type in _CORPORATE_ENTITY_TYPES:
        return "corporate"
    return "environment"


# cluster_types that represent market *reactions* (price/opinion movements) as
# opposed to *actions* (things that happened). Multi-hop causal-chain queries
# typically want to skip reactions. See docs/graph_edge_design.md §2.1.
_REACTION_CLUSTER_TYPES: frozenset[str] = frozenset({
    UnitType.STOCK_PRICE_CHANGE.value,
    UnitType.PRICE_CHANGE.value,
    UnitType.SECTOR_PERFORMANCE.value,
    UnitType.MARKET_ANALYSIS.value,
    UnitType.INDUSTRY_ANALYSIS.value,
    UnitType.RATING_CHANGE.value,
})


def derive_edge_nature(cluster_type: str) -> str:
    """Classify an INVOLVED_IN edge's nature as ``action`` or ``reaction``.

    Reaction = price/market/rating movement types; everything else is an
    action (something that happened). Used to prune derivative market noise
    from causal-chain multi-hop traversal.
    """
    if cluster_type in _REACTION_CLUSTER_TYPES:
        return "reaction"
    return "action"


# ---------------------------------------------------------------------------
# Direct edge (Entity → Entity) relation-type normalization
# ---------------------------------------------------------------------------

# The 19 relation_type values the extractor emits (knowledge_extractor.py
# prompt). Each maps to one of the 4 direct-edge types with a subtype, OR to
# None if it's a one-off event (those stay in EventCluster, never become a
# direct edge — see docs/graph_edge_design.md §1.3 stability threshold).
#
# Tuple = (direct_edge_type, subtype). None = do not create a direct edge.
_RELATION_TYPE_TO_DIRECT_EDGE: dict[str, tuple[str, str] | None] = {
    # OWNERSHIP — equity / control changes
    "控股": ("OWNERSHIP", "股权控制"),
    "增持": ("OWNERSHIP", "股权变动"),
    "减持": ("OWNERSHIP", "股权变动"),
    # GOVERNANCE — governance / oversight
    "高管任职": ("GOVERNANCE", "任职"),
    "监管": ("GOVERNANCE", "监管"),
    # COMMERCIAL — commercial cooperation
    "合作": ("COMMERCIAL", "合作"),
    "投资": ("COMMERCIAL", "投资"),
    "供应": ("COMMERCIAL", "供应"),
    "并购": ("COMMERCIAL", "并购"),
    "收购": ("COMMERCIAL", "收购"),
    # RISK — risk-linked / adversarial
    "竞争": ("RISK", "竞争"),
    "诉讼": ("RISK", "诉讼"),
    "制裁": ("RISK", "制裁"),
    "处罚": ("RISK", "处罚"),
    # One-off events → no direct edge (stay in EventCluster)
    "袭击": None,
    "签署": None,
    "谴责": None,
    "威胁": None,
    "反对": None,
}


def normalize_relation_type(raw: str) -> tuple[str | None, str | None]:
    """Map a free-text ``relation_type`` to a direct-edge ``(type, subtype)``.

    Returns ``(type, subtype)`` for stable structural relations that should
    become an Entity→Entity direct edge, or ``(None, None)`` for one-off
    events (袭击/签署/谴责/威胁/反对) that must stay in EventCluster.

    The 19 canonical relation_types from the extraction prompt are mapped
    explicitly. Unknown values (LLM drift, future extractor changes) return
    ``(None, None)`` — conservative: when in doubt, don't create a direct
    edge, let it live as an event.

    See docs/graph_edge_design.md §1.3 (stability threshold) and §3.1.
    """
    if not raw or not raw.strip():
        return (None, None)
    mapped = _RELATION_TYPE_TO_DIRECT_EDGE.get(raw.strip())
    if mapped is None:
        return (None, None)
    return mapped
