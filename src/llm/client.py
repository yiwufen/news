"""
LLM 客户端工厂。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from anthropic import Anthropic

from src.llm.config import get_llm_config

# Anthropic SDK reads ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL from system
# env and uses them for auth/URL, which conflicts with third-party
# Anthropic-compatible APIs (e.g. ZhiPu). Clear them at import time.
for _var in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
    if _var in os.environ:
        del os.environ[_var]


def create_offline_llm_client() -> tuple[Anthropic, str]:
    """
    创建离线处理模块使用的 LLM 客户端。

    用于：新闻生成、知识抽取等批处理任务
    """
    config = get_llm_config()
    model = config.get_offline_model()
    return _create_client(model)


def _create_client(model: str) -> tuple[Anthropic, str]:
    """内部：创建客户端实例。"""
    config = get_llm_config()

    if not config.api_key:
        raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

    client = Anthropic(api_key=config.api_key, base_url=config.base_url)
    return client, model


def get_offline_max_tokens() -> int:
    """获取离线处理的 max_tokens 配置。"""
    return get_llm_config().get_offline_max_tokens()


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
