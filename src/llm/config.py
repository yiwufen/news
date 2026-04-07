"""
LLM 模型配置管理。

支持在线/离线场景分别配置模型。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM 模型配置，支持在线/离线场景分离配置。"""

    # 全局 API 配置
    api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    base_url: str | None = Field(default=None, alias="ANTHROPIC_API_BASE_URL")

    # 全局模型配置（向后兼容）
    default_model: str = Field(default="glm-5", alias="ANTHROPIC_MODEL")
    default_max_tokens: int = Field(default=4096, alias="ANTHROPIC_MAX_TOKENS")

    # 在线处理模块配置
    online_model: str | None = Field(default=None, alias="ONLINE_LLM_MODEL")
    online_max_tokens: int | None = Field(default=None, alias="ONLINE_LLM_MAX_TOKENS")

    # 离线处理模块配置
    offline_model: str | None = Field(default=None, alias="OFFLINE_LLM_MODEL")
    offline_max_tokens: int | None = Field(default=None, alias="OFFLINE_LLM_MAX_TOKENS")

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    def get_online_model(self) -> str:
        """获取在线处理使用的模型名称。"""
        return self.online_model or self.default_model

    def get_offline_model(self) -> str:
        """获取离线处理使用的模型名称。"""
        return self.offline_model or self.default_model

    def get_online_max_tokens(self) -> int:
        """获取在线处理使用的 max_tokens。"""
        return self.online_max_tokens or self.default_max_tokens

    def get_offline_max_tokens(self) -> int:
        """获取离线处理使用的 max_tokens。"""
        return self.offline_max_tokens or self.default_max_tokens


@lru_cache
def get_llm_config() -> LLMConfig:
    """获取 LLM 配置单例。"""
    return LLMConfig()
