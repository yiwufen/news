"""
LLM 客户端工厂。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from anthropic import Anthropic


DEFAULT_MAX_TOKENS = 4096
DEFAULT_MODEL = "glm-5"


def create_llm_client() -> tuple[Anthropic, str]:
    """创建统一的 LLM 客户端。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

    base_url = os.environ.get("ANTHROPIC_API_BASE_URL")
    client = Anthropic(api_key=api_key, base_url=base_url)
    model = os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    return client, model


def extract_text_from_response(response: Any) -> str:
    """从响应对象中拼接文本块。"""
    content = ""
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            content += text
    return content


def parse_json_from_text(text: str, default: dict | None = None) -> dict:
    """从文本中提取 JSON。"""
    if not text:
        return default or {}

    try:
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(text)
    except json.JSONDecodeError:
        return default or {}
