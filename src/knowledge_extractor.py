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
3. source.doc_id、time.published_at、time.extracted_at 必填。
4. entities 保留原始 mention，entity_id 可以为空。
5. 发现不确定或冲突信息时，不要裁决对错，只标记 conflict_status。
# 实体抽取规范（严格）
entities 只能包含以下五类具名实体：
- Company：公司、企业（如「腾讯控股」「特斯拉」）
- Organization：政府机构、国际组织、协会（如「美联储」「联合国」）
- Person：具体人名（如「特朗普」「马斯克」），不要放泛指角色（如「记者」「员工」）
- Product：具体产品或基金名称（如「iPhone 16」「恒生指数基金」）
- Asset：具体资产（如「某地块」「某专利」）

以下内容**绝不能**作为 entity mention：
- 数值、金额、百分比（如「1.03亿元」「13%」「100」）
- 股票代码（如「002695.SZ」）
- 价格、点数（如「144美元/桶」「14445点」）
- 国家、地区、省市、海峡（如「中国」「伊朗」「山东」「上海」「霍尔木兹海峡」）
- 货币名称（如「美元」「人民币」）
- 抽象概念（如「市场」「价格」「行业」「停火」「增长」「经济增长」）
- 泛指角色词（如「记者」「员工」「用户」「股东」「董事会」）
- 时间表达、季度（如「2025年」「Q4」「上半年」）
- 财务指标/术语（如「营业收入」「净利润」「A股」「现金红利」「股票」）
- 指数/ETF/合约（如「恒生指数」「标普500指数」「主力合约」）
- 代词/指代（如「我国」「本公司」「该集团」）
- 军事泛指（如「美军」「伊朗军队」）
# 实体命名规范
- 如果提示中包含「已知实体参考」，请优先使用其中的标准名称作为 entities.mention
- 只有在已知实体列表中没有匹配项时，才使用文档中的原始表述
- 这有助于保持实体命名的一致性
# unit_type 分类规范（严格）
unit_type 只能是以下类型之一，不要使用其他值：
- financial_performance: 财务业绩、财报、营收、利润
- stock_price_change: 股价变动、涨跌
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
如果不确定，选择最接近的类别。
# 输出要求
- 只输出一个 JSON 对象，格式为 {"knowledge_units": [...]}
- knowledge_units 可以为空列表
- unit_kind 只能是 event 或 fact
"""

EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "extract_knowledge_units",
    "description": "从新闻文档中抽取 statement-level KnowledgeUnit 列表",
    "input_schema": {
        "type": "object",
        "properties": {
            "knowledge_units": {
                "type": "array",
                "items": KnowledgeUnit.model_json_schema(),
            }
        },
        "required": ["knowledge_units"],
    },
}


def build_extraction_prompt(
    doc: RawDocument,
    entity_context: list[EntityContext] | None = None,
) -> str:
    """Build the extraction prompt for one raw document with optional entity context."""
    payload = doc.model_dump(mode="json")
    prompt = f"""请从下面文档中抽取 KnowledgeUnit。
## 文档信息
- doc_id: {payload["doc_id"]}
- title: {payload["title"]}
- source_name: {payload["source_name"]}
- published_at: {payload["published_at"]}

## 正文
{payload["content"]}
"""
    if entity_context:
        prompt += build_entity_context_section(entity_context)
    return prompt


class KnowledgeExtractor:
    """KnowledgeUnit extractor with retry support for LLM format instability."""

    def __init__(self, enable_llm: bool | None = None, max_retries: int = 2):
        self.enable_llm = enable_llm if enable_llm is not None else True
        self.max_retries = max_retries
        self.client = None
        self.model = None
        self.max_tokens = get_offline_max_tokens()
        self._time_normalizer = TimeNormalizer()  # Cache instance
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
                return [
                    KnowledgeUnit.model_validate(unit)
                    for unit in normalized_units_payload
                ]

        raise ValueError("LLM did not return extract_knowledge_units")

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
        """Normalize event_time before KnowledgeUnit validation."""
        if not isinstance(unit_payload, dict):
            return unit_payload

        time_payload = unit_payload.get("time")
        if not isinstance(time_payload, dict):
            return unit_payload

        raw_time = time_payload.get("event_time")
        if raw_time is None:
            return unit_payload

        result = self._time_normalizer.normalize_event_time(raw_time, context)
        normalized_time_payload = dict(time_payload)
        normalized_time_payload["event_time"] = result.normalized_time
        normalized_time_payload["event_time_resolution"] = result.resolution_type
        if result.original_expression is not None:
            normalized_time_payload["raw_event_time_expression"] = (
                result.original_expression
            )

        normalized_unit_payload = dict(unit_payload)
        normalized_unit_payload["time"] = normalized_time_payload
        return normalized_unit_payload
