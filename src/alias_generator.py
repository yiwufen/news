"""Entity alias generation via offline LLM.

Generates common Chinese short names and English abbreviations for financial entities.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.entities import is_valid_entity_mention
from src.llm import create_offline_llm_client, get_offline_max_tokens

logger = logging.getLogger(__name__)

_ALIAS_SYSTEM_PROMPT = """你是一名金融实体别名生成器。
给定一个金融实体的全称、类型和可选标识符，生成该实体在中文金融新闻中常见的简称、缩写和别名。

规则：
- 只生成确实会在新闻中出现的别名，不要编造
- 别名长度至少 2 个字符，不允许单字
- 不要输出实体的全称本身
- 如果没有常见的别名，返回空列表

正例：
实体：国家发展和改革委员会（Organization）
→ ["发改委", "国家发改委", "NDRC"]

实体：宁德时代新能源科技股份有限公司（Company），标识符：300750.SZ
→ ["宁德时代", "宁德", "CATL"]

实体：比亚迪股份有限公司（Company），标识符：002594.SZ
→ ["比亚迪", "BYD"]

实体：中国平安保险（集团）股份有限公司（Company）
→ ["中国平安", "平安", "平安保险"]

实体：中国人民银行（Organization）
→ ["央行", "人行", "PBOC"]

反例：
实体：腾讯控股有限公司（Company）
→ ["腾讯控股", "Tx"] ✗（"腾讯控股"是全称中去掉"有限公司"后缀，不是通俗简称；"Tx"是编造的）
→ ["腾讯", "Tencent"] ✓

实体：贵州茅台酒股份有限公司（Company）
→ ["茅台", "贵州茅台"] ✓
→ ["贵茅", "茅"] ✗（"贵茅"不常见；"茅"是单字）
"""

_ALIAS_TOOL_SCHEMA: dict[str, Any] = {
    "name": "generate_entity_aliases",
    "description": "为金融实体生成常见简称和英文缩写",
    "input_schema": {
        "type": "object",
        "properties": {
            "aliases": {
                "type": "array",
                "items": {"type": "string", "minLength": 2},
                "maxItems": 8,
                "description": "常见别名列表（2-6字中文简称+英文缩写），不含全称本身。无常见别名时返回空列表。",
            }
        },
        "required": ["aliases"],
    },
}


class AliasGenerator:
    """Generate entity aliases using offline LLM."""

    def __init__(self, enable: bool = True):
        self.enable = enable
        self._client = None
        self._model = None
        self._max_tokens = get_offline_max_tokens()

    def _get_client(self) -> tuple[Any, str]:
        if self._client is None or self._model is None:
            self._client, self._model = create_offline_llm_client()
        return self._client, self._model

    def generate(
        self,
        entity_name: str,
        entity_type: str,
        identifiers: dict[str, str] | None = None,
    ) -> list[str]:
        """Generate common aliases for an entity.

        Returns a list of alias strings. Aliases that fail
        is_valid_entity_mention are dropped. API-level failures (quota
        exhausted, timeout, ...) propagate as exceptions so the caller can
        fail-fast rather than silently degrade — an alias-less entity is
        unmatchable by later documents using a different surface form, which
        is a root cause of duplicate entities.
        """
        if not self.enable:
            return []

        prompt = self._build_prompt(entity_name, entity_type, identifiers)
        raw = self._call_llm(prompt)

        # Post-filter: reject aliases that are invalid entity mentions
        # (e.g. country names, abstract concepts, generic role words).
        # This prevents aliases like "伊朗" for "伊朗国家男子足球队" that
        # would collide with the actual country entity.
        filtered = [a for a in raw if is_valid_entity_mention(a)]
        if len(filtered) < len(raw):
            dropped = set(raw) - set(filtered)
            logger.info(
                "Alias generator dropped %s for '%s': not valid entity mentions",
                sorted(dropped), entity_name,
            )
        return filtered

    def _build_prompt(
        self,
        entity_name: str,
        entity_type: str,
        identifiers: dict[str, str] | None,
    ) -> str:
        parts = [
            f"实体全称: {entity_name}",
            f"实体类型: {entity_type}",
        ]
        if identifiers:
            id_parts = [f"{k}: {v}" for k, v in identifiers.items()]
            parts.append(f"标识符: {', '.join(id_parts)}")
        parts.append("请生成该实体的常见别名。")
        return "\n".join(parts)

    def _call_llm(self, prompt: str) -> list[str]:
        client, model = self._get_client()
        response: Message = client.messages.create(
            model=model,
            max_tokens=256,
            system=_ALIAS_SYSTEM_PROMPT,
            tools=[_ALIAS_TOOL_SCHEMA],  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "generate_entity_aliases"},
            messages=[{"role": "user", "content": prompt}],
        )

        for block in response.content:
            if (
                isinstance(block, ToolUseBlock)
                and block.name == "generate_entity_aliases"
            ):
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if isinstance(payload, dict) and "aliases" in payload:
                    aliases = payload["aliases"]
                    if isinstance(aliases, list):
                        return [
                            a.strip()
                            for a in aliases
                            if isinstance(a, str) and len(a.strip()) >= 2
                        ]
        return []
