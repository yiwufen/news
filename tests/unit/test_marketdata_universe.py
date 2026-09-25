"""universe 本地符号解析测试。"""

from __future__ import annotations

from pathlib import Path

from src.marketdata.models import Instrument
from src.marketdata.store import MarketStore
from src.marketdata.universe import (
    DEFAULT_INDICES,
    _suffixed_to_secid,
    lookup_instruments,
    universe_is_stale,
)

import pytest


@pytest.fixture()
def store(tmp_path: Path) -> MarketStore:
    s = MarketStore(tmp_path / "market.db")
    s.replace_instruments(
        [
            Instrument("1.600519", "600519", 1, "贵州茅台", "GZMT", "stock"),
            Instrument("0.000001", "000001", 0, "平安银行", "PAYH", "stock"),
            Instrument("1.000001", "000001", 1, "上证指数", "SZZS", "index"),
            Instrument("116.00700", "00700", 116, "腾讯控股", "TXKG", "stock"),
            Instrument("0.300750", "300750", 0, "宁德时代", "NDSD", "stock"),
        ]
    )
    return s


class TestLookupInstruments:
    def test_secid_exact(self, store: MarketStore) -> None:
        result = lookup_instruments(store, "1.600519")
        assert [i.secid for i in result] == ["1.600519"]

    def test_suffixed_forms(self, store: MarketStore) -> None:
        assert [i.secid for i in lookup_instruments(store, "600519.SH")] == [
            "1.600519"
        ]
        assert [i.secid for i in lookup_instruments(store, "sh600519")] == [
            "1.600519"
        ]
        assert [i.secid for i in lookup_instruments(store, "00700.HK")] == [
            "116.00700"
        ]
        assert [i.secid for i in lookup_instruments(store, "HK00700")] == [
            "116.00700"
        ]

    def test_pure_symbol_multiple_candidates(self, store: MarketStore) -> None:
        # 000001 = 平安银行 + 上证指数：全部返回，不自动选择
        result = lookup_instruments(store, "000001")
        assert {i.secid for i in result} == {"0.000001", "1.000001"}

    def test_pure_symbol_unique(self, store: MarketStore) -> None:
        assert [i.secid for i in lookup_instruments(store, "600519")] == [
            "1.600519"
        ]

    def test_pinyin_prefix(self, store: MarketStore) -> None:
        assert [i.secid for i in lookup_instruments(store, "GZMT")] == [
            "1.600519"
        ]
        assert [i.secid for i in lookup_instruments(store, "gzmt")] == [
            "1.600519"
        ]

    def test_name_exact(self, store: MarketStore) -> None:
        assert [i.secid for i in lookup_instruments(store, "贵州茅台")] == [
            "1.600519"
        ]

    def test_name_contains(self, store: MarketStore) -> None:
        assert [i.secid for i in lookup_instruments(store, "茅台")] == [
            "1.600519"
        ]

    def test_miss_returns_empty(self, store: MarketStore) -> None:
        assert lookup_instruments(store, "不存在的公司") == []
        assert lookup_instruments(store, "") == []

    def test_index_by_pinyin(self, store: MarketStore) -> None:
        # 硬编码指数表里恒生科技的 pinyin 即其通用英文代码
        assert lookup_instruments(store, "HSTECH") == []


class TestSuffixedToSecid:
    def test_forms(self) -> None:
        assert _suffixed_to_secid("600519.SH") == "1.600519"
        assert _suffixed_to_secid("sz000001") == "0.000001"
        assert _suffixed_to_secid("00700.hk") == "116.00700"
        assert _suffixed_to_secid("茅台.SH") is None
        assert _suffixed_to_secid("600519") is None


class TestUniverseStaleness:
    def test_fresh_after_sync(self, store: MarketStore) -> None:
        assert universe_is_stale(store) is False

    def test_stale_when_never_synced(self, tmp_path: Path) -> None:
        assert universe_is_stale(MarketStore(tmp_path / "m.db")) is True


class TestReplacePreservesNonCn:
    def test_replace_keeps_hk_accumulated_rows(
        self, store: MarketStore
    ) -> None:
        """A股域全量替换不得清除港股 suggest 回写累积的行。"""
        store.replace_instruments(
            [Instrument("1.600519", "600519", 1, "贵州茅台", "GZMT", "stock")]
        )
        # 港股行保留；A股域整体替换（平安银行/上证指数被清掉）
        assert store.get_instrument("116.00700") is not None
        assert store.get_instrument("0.000001") is None
        assert store.get_instrument("1.600519") is not None

    def test_replace_overwrites_existing_non_deleted_rows(
        self, store: MarketStore
    ) -> None:
        """未删除域的同 secid 行（如硬编码港股指数）按 REPLACE 覆盖。"""
        new_hsi = Instrument("100.HSI", "HSI", 100, "恒生指数", "HSZS", "index")
        store.upsert_instrument(new_hsi)
        store.replace_instruments([new_hsi])
        assert store.get_instrument("100.HSI") is not None


def test_default_indices_shape() -> None:
    secids = {i.secid for i in DEFAULT_INDICES}
    assert secids == {
        "1.000001",
        "0.399001",
        "0.399006",
        "100.HSI",
        "100.HSTECH",
    }
    assert all(i.asset_type == "index" for i in DEFAULT_INDICES)
