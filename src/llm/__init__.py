"""
LLM 客户端模块。
"""

from src.llm.client import (
    create_offline_llm_client,
    extract_text_from_response,
    get_offline_max_tokens,
    parse_json_from_text,
)
from src.llm.config import LLMConfig, get_llm_config

__all__ = [
    # 客户端工厂
    "create_offline_llm_client",
    # 配置
    "LLMConfig",
    "get_llm_config",
    # 工具函数
    "extract_text_from_response",
    "parse_json_from_text",
    "get_offline_max_tokens",
]
