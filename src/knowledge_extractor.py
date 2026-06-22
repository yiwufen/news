"""
KnowledgeUnit extraction service.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.entity_context_filter import EntityContext, build_entity_context_section
from src.knowledge_base import KnowledgeUnit, RawDocument
from src.llm import create_offline_llm_client, get_offline_max_tokens
from src.time_normalization import TimeNormalizationContext, TimeNormalizer

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一名金融知识工程助手，负责从新闻文档中抽取可溯源的 statement-level KnowledgeUnit。
# 核心要求
1. 每个 KnowledgeUnit 表示来源中的一次明确陈述，不要把多个事件强行合并。
2. evidence 至少保留 1 条可读证据片段。
3. source.doc_id、time.published_at、time.extracted_at 由系统自动填入，LLM 只需提供 time.event_time（必须解析为 ISO 8601 绝对日期时间，参照下方「时间解析规范」）。
4. 发现不确定或冲突信息时，不要裁决对错，只标记 conflict_status。
# 提取优先级（遇到边界 case 时按此顺序裁决）
1. 准确性 > 召回率（宁缺毋滥）
2. 具体具名实体 > 抽象概念
3. 有明确时间锚点的动态陈述 > 静态背景描述
# 时间解析规范
event_time 是事件发生的绝对时间，不是报道发布时间。
你已拥有 published_at 作为参考锚点，请据此将中文时间表达式解析为 ISO 8601 日期时间。

解析规则（优先级从高到低）：
1. 原文含明确日期（"4月3日"、"2025年Q1"、"3月15日下午"）→ 直接转为 "YYYY-MM-DDTHH:MM:SSZ"，设 event_time_resolution = "explicit"
2. 原文含相对时间（"昨天"、"上周五"、"3天前"）→ 基于 published_at 推算绝对日期，设 event_time_resolution = "contextual"
3. 原文含模糊时间（"近期"、"近日"、"本月初"）→ 基于 published_at 取最合理的绝对日期估计，设 event_time_resolution = "contextual"，并设 time_grain：
   - "月"级模糊（"本月初"、"上个月"）→ time_grain = "month"
   - "季度"级模糊（"本季度"、"Q1"）→ time_grain = "quarter"，日期取季度末日
   - "年"级模糊（"今年初"、"去年"）→ time_grain = "year"，日期取年份首日
4. 原文无时间表达 → event_time = published_at，event_time_resolution = "contextual"（报道行为本身就是事件）
5. 陈述是预测/展望/规划目标时（如"预计2030年…"、"到2100年…"、"2025~2035年累计"）→ event_time 必须取 published_at（报道时间），不得取目标年份。预测/规划的目标时间不属于事件发生时间。

正例：
原文："宁德时代4月3日发布财报" + published_at: 2026-04-05
→ event_time: "2026-04-03T00:00:00Z", event_time_resolution: "explicit", time_grain: "day"

原文："昨日涨停" + published_at: 2026-04-05
→ event_time: "2026-04-04T00:00:00Z", event_time_resolution: "contextual", time_grain: "day"

原文："近期与特斯拉签署合作协议" + published_at: 2026-04-05
→ event_time: "2026-03-29T00:00:00Z", event_time_resolution: "contextual", time_grain: "day"

原文："今年Q1营收同比增长15%" + published_at: 2026-04-05
→ event_time: "2026-03-31T00:00:00Z", event_time_resolution: "contextual", time_grain: "quarter"

原文："比亚迪发布新品" + published_at: 2026-04-05（无时间词）
→ event_time: "2026-04-05T00:00:00Z", event_time_resolution: "contextual", time_grain: "day"

反例：
原文："昨日涨停" + published_at: 2026-04-05
→ event_time: "昨天" ✗（必须解析为绝对日期，不能照抄原文）

原文："近期签署协议" + published_at: 2026-04-05
→ event_time: null ✗（即使是模糊时间也应给出最佳估计，不是 null）

原文："比亚迪发布新品" + published_at: 2026-04-05（无时间词）
→ event_time: null ✗（无时间表达时 event_time = published_at，不是 null）

原文："Q1业绩超预期" + published_at: 2026-04-05
→ event_time: "2026-03-31T00:00:00Z", time_grain: "day" ✗（季度表达式应标记 time_grain = "quarter"）

原文："美银预计到2030年半导体市场规模达2万亿美元" + published_at: 2026-04-05
→ event_time: "2026-04-05T00:00:00Z", event_time_resolution: "contextual" ✓（预测目标年不是事件发生时间，应取报道时间）
→ event_time: "2030-12-31T00:00:00Z" ✗（这是预测目标年，不是事件发生时间）
# 实体抽取规范
entities 只能包含具名实体——现实世界中具有特定专有名称的对象。
- Company：具体企业（腾讯控股、比亚迪、锦鸡股份）
- Organization：具体机构（发改委、美联储、国务院）
- Person：特定人名（马斯克、刘鹤、鲍威尔）
- Product：有品牌名的具体产品（iPhone 16、麒麟芯片）

重要规则：
- entities 可以为空列表。陈述中没有具名实体时，不要硬造。
- 宁可漏提一个实体，也不要把非实体（概念、指标、时间词、行业泛称、协议名、政策名）塞进 entities。
- 资产（如股权、房产）不要作为实体提取，应通过 relation_hints 表达。
- 协议、条约、政策、法案（如美伊协议、巴黎协定、芯片法案）不是实体，它们是事件或政策，不要提取。
- 单字中文不允许作为实体 mention。遇到单字缩写/简称（无论国别、省份、机构）时必须展开为全称。例如："以"→"以色列"、"美"→"美国"、"粤"→"广东"、"浙"→"浙江"。
- 如果提示中包含「已知实体参考」，优先使用其中的标准名称作为 mention。

示例：

原文："腾讯控股发布2025年Q1财报，净利润425亿元，同比增长15%"
→ entities: [{"mention": "腾讯控股", "entity_type": "Company"}]
  "净利润"、"425亿元"、"Q1" 都不是实体。

原文："算力租赁概念股普遍上涨，多只股票涨停或涨超10%"
→ entities: []
  "算力租赁"是行业概念，不是具名实体。

原文："美联储宣布维持利率不变，鲍威尔表示将继续关注通胀数据"
→ entities: [{"mention": "美联储", "entity_type": "Organization"},
              {"mention": "鲍威尔", "entity_type": "Person"}]

原文："恒大地产转让所持盛京银行全部股权"
→ entities: [{"mention": "恒大地产", "entity_type": "Company"},
              {"mention": "盛京银行", "entity_type": "Company"}]
  "盛京银行全部股权"是资产描述，不作为实体，通过 relation_hints 表达转让关系。

原文："新兴产业逐步成为投资增长的新引擎"
→ entities: []
  没有具名实体，整条陈述通过 summary 保留即可。

原文："美伊协议达成后，国际油价大幅下跌"
→ entities: []
  "美伊协议"是协议名，不是具名实体，通过 summary 表达即可。

identifiers 字段填写规范（严格）：
- identifiers 只填机器可匹配的稳定唯一标识。键名固定为标识类型，值填标识符本身。
- 允许的键：ticker（证券代码，如 300750.SZ、0981.HK、AAPL）、isin（国际证券识别码）、uscc（统一社会信用代码）、cusip、wkn。
- Company/Product 类实体：仅当原文明确出现上述标识时才填入；未出现则留空 {}。
- Person/Organization：通常无稳定标识，留空 {}。
- 禁止填入角色、职位、国籍、代表团名、部门、行业描述等自然语言（如 "美国总统"、"伊朗谈判代表团"、"科技公司"）。
- 宁可不填，也不要填入语义描述。键名必须从允许列表中选择，不得自造。

示例：
原文："宁德时代（300750.SZ）发布2025年Q1财报"
→ entities: [{"mention": "宁德时代", "entity_type": "Company", "identifiers": {"ticker": "300750.SZ"}}]

原文："比亚迪股份（1211.HK）获南向资金增持"
→ entities: [{"mention": "比亚迪股份", "entity_type": "Company", "identifiers": {"ticker": "1211.HK"}}]

原文："美联储主席鲍威尔表示将继续关注通胀数据"
→ entities: [{"mention": "美联储", "entity_type": "Organization", "identifiers": {}},
              {"mention": "鲍威尔", "entity_type": "Person", "identifiers": {}}]
  "美联储主席"是角色描述，不是标识符。
# 关系抽取规范（严格）
如果陈述中包含实体间的明确互动或关联，请在 relation_hints 中提取：
1. subject_mention 与 object_mention 必须是你在 entities 列表中提取的精确 mention（一字不差）。
2. relation_type 必须简练且标准化，只能从以下列表中选择（若无合适项则不提取）：
   [合作, 投资, 并购, 竞争, 供应, 监管, 处罚, 诉讼, 高管任职,
    控股, 收购, 减持, 增持, 制裁, 袭击, 签署, 谴责, 威胁, 反对]
3. 不确定的推测不要作为关系提取。
示例：

原文："腾讯斥资4亿美元投资快手"
→ relation_hints: [{"relation_type": "投资", "subject_mention": "腾讯", "object_mention": "快手"}]

原文："恒大地产转让所持盛京银行全部股权"
→ relation_hints: [{"relation_type": "减持", "subject_mention": "恒大地产", "object_mention": "盛京银行"}]

原文："两家公司在供应链领域有长期合作"
→ 不要提取关系（"长期合作"是模糊描述，不是明确互动）
# unit_type 分类规范（严格）
unit_type 只能是以下类型之一，不要使用其他值：
- financial_performance: 财务业绩、财报、营收、利润
- stock_price_change: 股价变动、涨跌。重要：不要为纯粹的股价涨跌数字提取此类 KU。只有当陈述包含因果归因（如因...、受...影响、得益于、推动、带动）时才提取。例如：不要提取"比亚迪涨了3%"、"收盘跌2.1%"；应该提取"比亚迪涨停，因Q3净利超预期"、"受美联储降息影响，科技股集体上涨"。
- price_change: 商品/资产价格变动
- market_analysis: 市场分析、行情、趋势
- dividend: 分红、派息
- ipo: IPO、上市
- restructuring: 资产重组、并购
- investment: 投资、融资
- product_launch: 产品发布、研发
- business_strategy: 企业战略、经营范围
- company_establishment: 企业设立
- executive_change: 高管变动、实控人变动
- legal_proceeding: 诉讼、法律
- regulatory_action: 监管处罚、行政
- policy_announcement: 政策发布、变动
- sanction: 制裁、禁运
- debt_default: 债务违约
- equity_pledge: 股权质押
- risk_warning: 风险提示、警告
- economic_data: 经济数据、指标
- trade_data: 贸易数据
- sector_performance: 板块、行业表现
- diplomatic_event: 外交声明、访问
- military_action: 军事行动
- political_statement: 政治声明
- announcement: 声明、公告
- meeting: 会议
- industry_analysis: 行业分析、趋势
- other: 无法归入以上类别
如果不确定，归入 other。不要使用列表外的值。
示例：

原文："比亚迪涨停，因Q3净利超预期"
→ unit_type: stock_price_change（有因果归因）

原文："比亚迪涨了3%"
→ 不要单独提取为 KU（纯粹的股价涨跌数字，无因果归因）

原文："央行宣布降准50个基点"
→ unit_type: policy_announcement

原文："鸿海精密宣布投资10亿美元在印度建厂"
→ unit_type: investment
# 输出前自检（必须验证）
1. 每条 relation_hint 的 subject_mention 和 object_mention 必须在 entities 列表中精确出现
2. evidence.text 必须是正文的原文片段（逐字匹配，不可改写或总结）
3. unit_type 必须是上述枚举值之一
# 输出要求
- 只输出一个 JSON 对象，格式为 {"knowledge_units": [...]}
- knowledge_units 可以为空列表
- unit_kind 只能是 event 或 fact
"""

EXTRACTION_TOOL_SCHEMA: dict[str, Any]


def _build_extraction_tool_schema() -> dict[str, Any]:
    """Build tool schema with enum constraints for classification fields."""
    from src.schemas.enums import UnitType

    ku_schema = KnowledgeUnit.model_json_schema()
    defs = ku_schema.get("$defs", {})

    relation_type_enum = [
        "合作", "投资", "并购", "竞争", "供应", "监管", "处罚", "诉讼", "高管任职",
        "控股", "收购", "减持", "增持", "制裁", "袭击", "签署", "谴责", "威胁", "反对",
    ]
    entity_type_enum = ["Company", "Organization", "Person", "Product"]
    unit_type_enum = [t.value for t in UnitType]

    ku_schema["properties"]["unit_type"]["enum"] = unit_type_enum
    defs["EntityRef"]["properties"]["entity_type"]["enum"] = entity_type_enum
    defs["EntityRef"]["properties"]["mention"]["minLength"] = 2
    defs["RelationHint"]["properties"]["relation_type"]["enum"] = relation_type_enum

    # Inject identifiers field description: constrain to stable machine-matchable
    # identifiers (ticker/isin/uscc), forbid natural-language role descriptions.
    entity_ref_props = defs["EntityRef"]["properties"]
    entity_ref_props.setdefault("identifiers", {})
    entity_ref_props["identifiers"]["description"] = (
        "机器可匹配的稳定唯一标识。键名为标识类型，仅允许 ticker/isin/uscc/cusip/wkn，"
        "值为标识符本身（如 ticker=300750.SZ）。仅填证券代码、ISIN、统一社会信用代码等；"
        "禁止填角色、职位、国籍、部门等自然语言描述。原文未明确出现时留空 {}。"
    )

    # Inject time field descriptions into TimeRef schema
    time_ref = defs.get("TimeRef", {})
    time_ref_props = time_ref.get("properties", {})
    time_ref_props.setdefault("event_time", {})
    time_ref_props["event_time"]["description"] = (
        "事件发生的绝对时间（ISO 8601）。基于 published_at 解析中文时间表达式。"
        "例如：published_at=2026-04-05 时，'昨天'→'2026-04-04T00:00:00Z'，"
        "'近期'→'2026-03-29T00:00:00Z'，无时间词→'2026-04-05T00:00:00Z'。"
    )
    time_ref_props.setdefault("event_time_resolution", {})
    time_ref_props["event_time_resolution"]["description"] = (
        "时间解析类型：'explicit'（原文明确日期）、'contextual'（基于 published_at 推算）、'unresolved'（无法解析）"
    )
    time_ref_props["event_time_resolution"]["enum"] = ["explicit", "contextual", "unresolved"]
    time_ref_props.setdefault("time_grain", {})
    time_ref_props["time_grain"]["description"] = (
        "时间粒度：'day'（精确到天）、'month'（月级模糊）、'quarter'（季度）、'year'（年级模糊）"
    )
    time_ref_props["time_grain"]["enum"] = ["day", "month", "quarter", "year"]
    time_ref_props["time_grain"]["default"] = "day"

    return {
        "name": "extract_knowledge_units",
        "description": "从新闻文档中抽取 statement-level KnowledgeUnit 列表",
        "input_schema": {
            "type": "object",
            "properties": {
                "knowledge_units": {
                    "type": "array",
                    "items": ku_schema,
                }
            },
            "required": ["knowledge_units"],
        },
    }


EXTRACTION_TOOL_SCHEMA = _build_extraction_tool_schema()


def build_extraction_prompt(
    doc: RawDocument,
    entity_context: list[EntityContext] | None = None,
) -> str:
    """Build the extraction prompt for one raw document with optional entity context."""
    payload = doc.model_dump(mode="json")
    parts = [
        f"## 参考时间（published_at）\n{payload['published_at']}\n",
        f"## 正文\n{payload['content']}\n",
        f"## 文档信息\ndoc_id: {payload['doc_id']} | title: {payload['title']} | source: {payload['source_name']}\n",
    ]
    if entity_context:
        parts.append(build_entity_context_section(entity_context))
    return "\n".join(parts)


class KnowledgeExtractor:
    """KnowledgeUnit extractor with retry support for LLM format instability."""

    def __init__(self, enable_llm: bool | None = None, max_retries: int = 2):
        self.enable_llm = enable_llm if enable_llm is not None else True
        self.max_retries = max_retries
        self.client = None
        self.model = None
        self.max_tokens = get_offline_max_tokens()
        self._time_normalizer = TimeNormalizer()
        logger.debug(f"KnowledgeExtractor initialized (enable_llm={self.enable_llm}, max_retries={self.max_retries})")

    def extract(
        self,
        document: RawDocument,
        entity_context: list[EntityContext] | None = None,
    ) -> list[KnowledgeUnit]:
        """Extract KnowledgeUnits for one document with optional entity context."""
        if not self.enable_llm:
            raise RuntimeError(
                "KnowledgeExtractor is configured without LLM extraction; heuristic extraction has been removed"
            )

        logger.debug(f"Extracting KnowledgeUnits from document: {document.doc_id}")
        if entity_context:
            logger.debug(f"Using entity context with {len(entity_context)} entities")
        try:
            units = self._extract_with_llm(document, entity_context)
            logger.info(f"Extracted {len(units)} KnowledgeUnits from {document.doc_id}")
            return units
        except Exception as exc:
            logger.error(f"Failed to extract from {document.doc_id}: {exc}")
            raise RuntimeError(
                f"KnowledgeUnit extraction failed for {document.doc_id}: {exc}"
            ) from exc

    def extract_batch(
        self,
        documents: list[RawDocument],
        entity_context: list[EntityContext] | None = None,
    ) -> dict[str, list[KnowledgeUnit]]:
        """Extract documents in batch with optional entity context."""
        return {
            document.doc_id: self.extract(document, entity_context)
            for document in documents
        }

    def _get_client(self) -> tuple[Any, str]:
        if self.client is None or self.model is None:
            self.client, self.model = create_offline_llm_client()
            logger.debug(f"LLM client initialized with model: {self.model}")
        return self.client, self.model

    def _extract_with_llm(
        self,
        document: RawDocument,
        entity_context: list[EntityContext] | None = None,
    ) -> list[KnowledgeUnit]:
        client, model = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response: Message = client.messages.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    system=SYSTEM_PROMPT,
                    tools=[EXTRACTION_TOOL_SCHEMA],  # type: ignore[arg-type]
                    tool_choice={"type": "tool", "name": "extract_knowledge_units"},
                    messages=[{
                        "role": "user",
                        "content": build_extraction_prompt(document, entity_context),
                    }],
                )
                return self._parse_llm_response(response, document)
            except ValueError as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"LLM format error for {document.doc_id} (attempt {attempt + 1}/{self.max_retries + 1}): {e}"
                    )
                    time.sleep(0.5 * (attempt + 1))  # 递增延迟
                else:
                    raise

        raise last_error or ValueError("LLM extraction failed")

    def _parse_llm_response(self, response: Message, document: RawDocument) -> list[KnowledgeUnit]:
        """Parse LLM response into KnowledgeUnit list."""
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_knowledge_units":
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    raise ValueError("extract_knowledge_units returned a non-object payload")
                units_payload = payload.get("knowledge_units")
                # 容错处理：None 或非列表类型触发重试
                if units_payload is None:
                    raise ValueError("LLM returned null knowledge_units")
                if not isinstance(units_payload, list):
                    raise ValueError(
                        f"LLM returned non-list knowledge_units (type={type(units_payload).__name__})"
                    )
                context = self._build_time_normalization_context(document)
                normalized_units_payload = [
                    self._normalize_unit_payload_time(unit, context)
                    for unit in units_payload
                ]
                # Normalize unit_type to canonical vocabulary
                from src.schemas.enums import normalize_unit_type
                for unit in normalized_units_payload:
                    if isinstance(unit, dict) and "unit_type" in unit:
                        unit["unit_type"] = normalize_unit_type(unit["unit_type"]).value
                units = [
                    KnowledgeUnit.model_validate(unit)
                    for unit in normalized_units_payload
                ]
                self._log_time_resolution_stats(document.doc_id, units)
                return units

        raise ValueError("LLM did not return extract_knowledge_units")

    @staticmethod
    def _log_time_resolution_stats(doc_id: str, units: list[KnowledgeUnit]) -> None:
        total = len(units)
        if total == 0:
            return
        resolved = 0
        by_resolution: dict[str, int] = {}
        for u in units:
            if u.time.event_time is not None:
                resolved += 1
            r = u.time.event_time_resolution or "unresolved"
            by_resolution[r] = by_resolution.get(r, 0) + 1
        rate = resolved / total * 100
        logger.info(
            "Time resolution for %s: %d/%d (%.0f%%) resolved, distribution=%s",
            doc_id, resolved, total, rate, by_resolution,
        )
        if rate < 50:
            logger.warning(
                "Low time resolution rate for %s: %.0f%% (%d/%d)",
                doc_id, rate, resolved, total,
            )

    def _build_time_normalization_context(
        self,
        document: RawDocument,
    ) -> TimeNormalizationContext:
        return TimeNormalizationContext(
            published_at=document.published_at,
            extracted_at=datetime.now(UTC),
            document_title=document.title,
        )

    def _normalize_unit_payload_time(
        self,
        unit_payload: Any,
        context: TimeNormalizationContext,
    ) -> Any:
        """Validate event_time from LLM extraction."""
        if not isinstance(unit_payload, dict):
            return unit_payload

        time_payload = unit_payload.get("time")
        if not isinstance(time_payload, dict):
            return unit_payload

        normalized_time_payload = dict(time_payload)
        # System-owned fields: published_at and extracted_at must come from the
        # pipeline, never from the LLM. The LLM historically hallucinated these
        # (e.g. extracted_at=2025-01-18 for a 2026-06 article), which broke
        # TimeNormalizer's future-check baseline. Overwrite unconditionally.
        normalized_time_payload["published_at"] = context.published_at.isoformat()
        normalized_time_payload["extracted_at"] = context.extracted_at.isoformat()

        raw_time = time_payload.get("event_time")
        if raw_time is None:
            # No event_time from LLM — leave as-is for KnowledgeUnit validation
            normalized_unit_payload = dict(unit_payload)
            normalized_unit_payload["time"] = normalized_time_payload
            return normalized_unit_payload

        result = self._time_normalizer.normalize_event_time(
            raw_time,
            context,
            resolution_type=time_payload.get("event_time_resolution"),
            time_grain=time_payload.get("time_grain", "day"),
        )

        # Future event_time was hard-clamped to None by TimeNormalizer (e.g. a
        # forecast target year like "by 2030"). Fall back to published_at so the
        # KU keeps a valid temporal anchor — the report publication is the
        # closest legitimate event time for a forward-looking statement.
        is_future_clamp = (
            result.normalized_time is None
            and result.resolution_type == "unresolved"
            and result.validation_error is not None
            and "future" in result.validation_error
        )
        if is_future_clamp:
            normalized_time_payload["event_time"] = context.published_at
            normalized_time_payload["event_time_resolution"] = "contextual"
        else:
            normalized_time_payload["event_time"] = result.normalized_time
            normalized_time_payload["event_time_resolution"] = result.resolution_type
        normalized_time_payload["time_grain"] = result.time_grain
        if result.validation_error:
            if is_future_clamp:
                logger.info(
                    "Future event_time for doc %s reset to published_at (%s)",
                    unit_payload.get("source", {}).get("doc_id", "?"),
                    context.published_at.isoformat(),
                )
            else:
                logger.warning(
                    "Time validation error for doc %s: %s",
                    unit_payload.get("source", {}).get("doc_id", "?"),
                    result.validation_error,
                )

        normalized_unit_payload = dict(unit_payload)
        normalized_unit_payload["time"] = normalized_time_payload
        return normalized_unit_payload
