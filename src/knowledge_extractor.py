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
4. 发现不确定或冲突信息时，不要裁决对错，只标记 conflict_status。
# 实体抽取规范
entities 只能包含具名实体——现实世界中具有特定专有名称的对象。
- Company：具体企业（腾讯控股、比亚迪、锦鸡股份）
- Organization：具体机构（发改委、美联储、国务院）
- Person：特定人名（马斯克、刘鹤、鲍威尔）
- Product：有品牌名的具体产品（iPhone 16、麒麟芯片）

重要规则：
- entities 可以为空列表。陈述中没有具名实体时，不要硬造。
- 宁可漏提一个实体，也不要把非实体（概念、指标、时间词、行业泛称）塞进 entities。
- 资产（如股权、房产）不要作为实体提取，应通过 relation_hints 表达。
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
# 关系抽取规范（严格）
如果陈述中包含实体间的明确互动或关联，请在 relation_hints 中提取：
1. subject_mention 与 object_mention 必须是你在 entities 列表中提取的精确 mention（一字不差）。
2. relation_type 必须简练且标准化，只能从以下列表中选择（若无合适项则不提取）：
   [合作, 投资, 并购, 竞争, 供应, 监管, 处罚, 诉讼, 高管任职,
    控股, 收购, 减持, 增持, 制裁, 袭击, 签署, 谴责, 威胁, 反对]
3. 不确定的推测不要作为关系提取。
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
