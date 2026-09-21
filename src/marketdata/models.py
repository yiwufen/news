"""marketdata 数据模型。

secid 统一采用东财体系 ``{market}.{symbol}``：
沪 A/沪指数前缀 1，深 0，港 116，港股指数 100（如 ``100.HSI``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Instrument:
    """股票主数据条目（instruments 表的一行）。"""

    secid: str
    symbol: str
    market: int
    name: str
    pinyin: str | None
    asset_type: str  # "stock" | "index"


@dataclass(frozen=True)
class Quote:
    """一次行情快照。停牌标的数值字段可为 None。"""

    secid: str
    symbol: str
    name: str
    price: float | None
    change: float | None
    change_pct: float | None
    open: float | None
    high: float | None
    low: float | None
    pre_close: float | None
    volume: float | None  # A股单位:手；港股:股
    amount: float | None  # 成交额，A股市值货币单位（元/港元）
    market_time: datetime
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "secid": self.secid,
            "symbol": self.symbol,
            "name": self.name,
            "price": self.price,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "pre_close": self.pre_close,
            "volume": self.volume,
            "amount": self.amount,
            "market_time": self.market_time.isoformat(),
            "source": self.source,
        }


@dataclass(frozen=True)
class KlineBar:
    """一根日K（前复权）。"""

    secid: str
    trade_date: str  # ISO 日期 "2026-09-21"
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
