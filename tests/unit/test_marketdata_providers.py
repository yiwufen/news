"""marketdata provider 解析测试。

fixtures 为 2026-09-21 盘中实测抓取的真实响应（含停牌、港股、指数、
干扰项等真实形态），锁定上游 schema 契约。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.marketdata.providers.eastmoney import (
    parse_kline_payload,
    parse_quote_payload,
    parse_suggest_payload,
)
from src.marketdata.providers.sina import parse_sina_list_rows
from src.marketdata.providers.tencent import (
    parse_tencent_klines,
    parse_tencent_quotes,
    secid_to_tencent,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "marketdata"


def _load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# EastMoney
# ---------------------------------------------------------------------------


class TestParseQuotePayload:
    def test_real_payload_a_share(self) -> None:
        quotes = parse_quote_payload(_load_json("eastmoney_ulist.json"))
        assert "1.600519" in quotes
        q = quotes["1.600519"]
        assert q.symbol == "600519"
        assert q.name == "贵州茅台"
        assert q.price == pytest.approx(1251.81)
        assert q.pre_close == pytest.approx(1257.12)
        assert q.change == pytest.approx(1251.81 - 1257.12)
        assert q.change_pct == pytest.approx(-0.42)
        assert q.open == pytest.approx(1259.0)
        assert q.high == pytest.approx(1259.95)
        assert q.low == pytest.approx(1250.8)
        assert q.volume == pytest.approx(14752)
        assert q.amount == pytest.approx(1849347311.0)
        assert q.source == "eastmoney"
        assert q.market_time.isoformat().startswith("2026-09-21T")

    def test_real_payload_hk_and_index(self) -> None:
        quotes = parse_quote_payload(_load_json("eastmoney_ulist.json"))
        assert "116.00700" in quotes and quotes["116.00700"].name == "腾讯控股"
        assert "1.000001" in quotes and quotes["1.000001"].name == "上证指数"
        assert "100.HSI" in quotes and quotes["100.HSI"].name == "恒生指数"

    def test_suspended_stock_fields_become_none(self) -> None:
        payload = {
            "rc": 0,
            "data": {
                "diff": [
                    {
                        "f2": "-",
                        "f3": "-",
                        "f12": "600519",
                        "f13": 1,
                        "f14": "贵州茅台",
                        "f18": "-",
                        "f124": 1789961050,
                    }
                ]
            },
        }
        q = parse_quote_payload(payload)["1.600519"]
        assert q.price is None
        assert q.change is None
        assert q.name == "贵州茅台"

    def test_rc_nonzero_raises(self) -> None:
        with pytest.raises(ValueError, match="rc"):
            parse_quote_payload({"rc": -1, "data": {}})

    def test_missing_diff_raises(self) -> None:
        with pytest.raises(ValueError, match="diff"):
            parse_quote_payload({"rc": 0, "data": None})

    def test_item_missing_required_field_raises(self) -> None:
        payload = {
            "rc": 0,
            "data": {"diff": [{"f12": "600519", "f13": 1}]},  # 无 f14/f124
        }
        with pytest.raises(ValueError, match="f14/f124"):
            parse_quote_payload(payload)


class TestParseKlinePayload:
    def test_real_payload(self) -> None:
        bars = parse_kline_payload(_load_json("eastmoney_kline.json"))
        assert len(bars) == 5
        assert all(b.secid == "1.600519" for b in bars)
        assert bars[0].trade_date == "2026-09-15"
        assert bars[0].open == pytest.approx(1281.00)
        assert bars[0].close == pytest.approx(1272.75)
        assert bars[-1].trade_date == "2026-09-21"
        assert bars[-1].close == pytest.approx(1252.00)
        assert bars[-1].volume == pytest.approx(14010)

    def test_malformed_row_raises(self) -> None:
        payload = {"data": {"market": 1, "code": "600519", "klines": ["2026-09-15"]}}
        with pytest.raises(ValueError, match="malformed"):
            parse_kline_payload(payload)

    def test_missing_klines_raises(self) -> None:
        with pytest.raises(ValueError, match="klines"):
            parse_kline_payload({"data": {"market": 1, "code": "600519"}})


class TestParseSuggestPayload:
    def test_filters_non_target_classify(self) -> None:
        result = parse_suggest_payload(
            _load_json("eastmoney_suggest_multi.json")
        )
        secids = [i.secid for i in result]
        # OTCBB 粉单干扰项被过滤，港股与指数保留
        assert secids == ["116.00700", "1.000001"]
        hk = result[0]
        assert hk.name == "腾讯控股"
        assert hk.pinyin == "TXKG"
        assert hk.asset_type == "stock"
        assert result[1].asset_type == "index"

    def test_single_hit(self) -> None:
        result = parse_suggest_payload(_load_json("eastmoney_suggest.json"))
        assert len(result) == 1
        assert result[0].secid == "1.600519"
        assert result[0].pinyin == "GZMT"


class TestParseSinaListRows:
    def test_real_rows_and_bj_filter(self) -> None:
        rows = json.loads(
            (FIXTURES / "sina_list.json").read_text(encoding="utf-8")
        )
        items = parse_sina_list_rows(rows)
        # 北交所前缀（bj）一期不覆盖，被过滤；沪深保留
        assert [i.secid for i in items] == ["1.600519", "0.000001"]
        assert items[0].name == "贵州茅台"
        assert items[0].asset_type == "stock"

    def test_missing_symbol_raises(self) -> None:
        with pytest.raises(ValueError, match="symbol/code"):
            parse_sina_list_rows([{"code": "600519", "name": "x"}])


# ---------------------------------------------------------------------------
# Tencent
# ---------------------------------------------------------------------------


class TestSecidToTencent:
    def test_all_markets(self) -> None:
        assert secid_to_tencent("1.600519") == "sh600519"
        assert secid_to_tencent("0.000001") == "sz000001"
        assert secid_to_tencent("116.00700") == "hk00700"
        assert secid_to_tencent("100.HSI") == "hkHSI"
        assert secid_to_tencent("garbage") is None


class TestParseTencentQuotes:
    def test_real_a_share(self) -> None:
        body = (FIXTURES / "tencent_sh.txt").read_text(encoding="utf-8")
        quotes = parse_tencent_quotes(body, {"1.600519": "sh600519"})
        q = quotes["1.600519"]
        assert q.name == "贵州茅台"
        assert q.price == pytest.approx(1251.89)
        assert q.pre_close == pytest.approx(1257.12)
        assert q.change == pytest.approx(-5.23)
        assert q.change_pct == pytest.approx(-0.42)
        assert q.high == pytest.approx(1259.95)
        assert q.low == pytest.approx(1250.80)
        # 腾讯 A股 amount 单位为万元，需换算成元
        assert q.amount == pytest.approx(184922 * 10000)
        assert q.market_time.isoformat().startswith("2026-09-21T11:24:07")

    def test_real_hk_share(self) -> None:
        body = (FIXTURES / "tencent_hk.txt").read_text(encoding="utf-8")
        quotes = parse_tencent_quotes(body, {"116.00700": "hk00700"})
        q = quotes["116.00700"]
        assert q.name == "腾讯控股"
        assert q.price == pytest.approx(427.200)
        assert q.pre_close == pytest.approx(419.000)
        assert q.change == pytest.approx(8.200)
        # 港股 amount 已是港元，无需换算
        assert q.amount == pytest.approx(3485108344.800)

    def test_row_not_in_wanted_raises(self) -> None:
        # 响应有行但都不在 wanted 映射里 = 调用方映射错误或响应异常，
        # 按源级失败处理而不是静默返回空
        body = (FIXTURES / "tencent_sh.txt").read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="no parsable rows"):
            parse_tencent_quotes(body, {"116.00700": "hk00700"})

    def test_garbage_body_raises(self) -> None:
        with pytest.raises(ValueError, match="no parsable rows"):
            parse_tencent_quotes("garbage\n", {"1.600519": "sh600519"})


class TestParseTencentKlines:
    def test_real_a_share_qfq(self) -> None:
        bars = parse_tencent_klines(
            _load_json("tencent_kline_a.json"), "1.600519", 5
        )
        assert len(bars) == 5
        assert all(b.secid == "1.600519" for b in bars)
        assert bars[0].trade_date == "2026-09-14"
        # 腾讯行序：日期,开,收,高,低,量；无成交额 → amount=0
        assert bars[0].open == pytest.approx(1277.27)
        assert bars[0].close == pytest.approx(1277.96)
        assert bars[0].high == pytest.approx(1285.53)
        assert bars[0].low == pytest.approx(1270.36)
        assert bars[0].volume == pytest.approx(16571.0)
        assert bars[0].amount == 0.0

    def test_real_hk_row_with_dict_suffix(self) -> None:
        """港股行尾带除权信息 dict 与附加字段：解析只取前 6 列。"""
        bars = parse_tencent_klines(
            _load_json("tencent_kline_hk.json"), "116.00700", 5
        )
        assert len(bars) == 5
        assert bars[0].trade_date == "2026-09-15"
        assert bars[0].open == pytest.approx(428.0)
        assert bars[0].close == pytest.approx(438.8)
        assert bars[0].volume == pytest.approx(21791117.0)

    def test_real_index_day_key(self) -> None:
        """指数无复权概念，上游用 day 键（qfqday 缺失时回退）。"""
        bars = parse_tencent_klines(
            _load_json("tencent_kline_index.json"), "1.000001", 5
        )
        assert len(bars) == 5
        assert bars[0].trade_date == "2026-09-14"
        assert bars[0].close == pytest.approx(3885.33)

    def test_lmt_trims_to_latest(self) -> None:
        bars = parse_tencent_klines(
            _load_json("tencent_kline_a.json"), "1.600519", 2
        )
        assert [b.trade_date for b in bars] == ["2026-09-17", "2026-09-18"]

    def test_missing_data_raises(self) -> None:
        with pytest.raises(ValueError, match="data missing"):
            parse_tencent_klines(
                {"code": 0, "msg": "", "data": {}}, "1.600519", 5
            )

    def test_malformed_row_raises(self) -> None:
        payload = {"code": 0, "data": {"sh600519": {"qfqday": [["2026-09-14"]]}}}
        with pytest.raises(ValueError, match="malformed"):
            parse_tencent_klines(payload, "1.600519", 5)

    def test_unmappable_secid_raises(self) -> None:
        with pytest.raises(ValueError, match="unmappable"):
            parse_tencent_klines({"code": 0, "data": {}}, "99.999999", 5)
