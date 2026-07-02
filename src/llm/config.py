"""
LLM 模型配置管理。

仅保留离线（批处理）场景的模型配置。在线意图解析服务已从检索层移除。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    """LLM 模型配置。

    仅保留离线（批处理抽取/生成）场景的模型配置。在线意图解析等实时
    LLM 服务已从检索服务移除，故 online_* 配置一并删除。
    """

    # 全局 API 配置
    api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    base_url: str | None = Field(default=None, alias="ANTHROPIC_API_BASE_URL")

    # 全局模型配置（默认值，离线未单独配置时回退到此）
    default_model: str = Field(default="glm-5", alias="ANTHROPIC_MODEL")
    default_max_tokens: int = Field(default=4096, alias="ANTHROPIC_MAX_TOKENS")

    # 离线处理模块配置（新闻生成、知识抽取等批处理任务）
    offline_model: str | None = Field(default=None, alias="OFFLINE_LLM_MODEL")
    offline_max_tokens: int | None = Field(default=None, alias="OFFLINE_LLM_MAX_TOKENS")

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    def get_offline_model(self) -> str:
        """获取离线处理使用的模型名称。"""
        return self.offline_model or self.default_model

    def get_offline_max_tokens(self) -> int:
        """获取离线处理使用的 max_tokens。"""
        return self.offline_max_tokens or self.default_max_tokens


@lru_cache
def get_llm_config() -> LLMConfig:
    """获取 LLM 配置单例。"""
    return LLMConfig()
