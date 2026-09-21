"""股票行情检索模块（主数据落库 + 行情实时直连）。

对外入口见 :mod:`src.marketdata.service` 的 :func:`get_service`。
设计文档：docs/design-issues/marketdata-mcp-design.md
"""

from src.marketdata.service import (
    AllSourcesUnavailable,
    MarketDataService,
    get_service,
    reset_service_singleton,
)

__all__ = [
    "AllSourcesUnavailable",
    "MarketDataService",
    "get_service",
    "reset_service_singleton",
]
