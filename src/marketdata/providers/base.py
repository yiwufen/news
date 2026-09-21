"""数据源适配层公共协议。

解析逻辑与网络访问分离：每个 provider 的 payload 解析是纯函数，
网络方法只负责请求与错误归一（统一抛 :class:`ProviderError`）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.marketdata.models import Instrument, KlineBar, Quote


class ProviderError(Exception):
    """单个数据源本次请求失败（网络/超时/schema 校验不通过）。

    上层 failover 链捕获后切换下一源；不带堆栈噪音，只带可读原因。
    """

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(f"[{provider}] {reason}")
        self.provider = provider
        self.reason = reason


class QuoteProvider(ABC):
    """行情源协议。实现类必须 ``name`` 唯一，用于熔断状态与日志。"""

    name: str

    @abstractmethod
    async def fetch_quotes(self, secids: list[str]) -> dict[str, Quote]:
        """批量拉取实时行情。

        返回 secid -> Quote 映射；上游缺失个别 secid（如退市）时允许缺项。
        整体失败（网络、反爬、schema 变形）必须抛 ProviderError。
        """


class HistoryProvider(ABC):
    """历史日K源协议（一期仅东财实现）。"""

    name: str

    @abstractmethod
    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[KlineBar]:
        """按需求拉取日K（升序返回）。失败抛 ProviderError。"""


class ListProvider(ABC):
    """主数据全量列表源（与行情源分域部署，隔离限流连坐）。"""

    name: str

    @abstractmethod
    async def fetch_instruments(self, node: str) -> list[Instrument]:
        """按市场的列表节点分页拉全量。失败抛 ProviderError。"""


class SearchProvider(ABC):
    """在线名称搜索（suggest）源，作冷门标的兜底。"""

    name: str

    @abstractmethod
    async def fetch_suggest(self, query: str) -> list[Instrument]:
        """名称/拼音/代码在线搜索，返回候选。失败抛 ProviderError。"""
