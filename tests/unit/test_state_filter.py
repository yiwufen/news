"""Tests for state-content admission filter (``src.pipeline.state_filter``).

样本全部来自生产库实测（2026-09-30）：丢弃例取自丢弃集抽样（0 误杀），
保留例覆盖两类出口（归因词/事件实质词）与类型限定。规格见
``docs/design-issues/state-vs-statement-routing.md`` §2.1。
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeUnit,
    SourceRef,
    TimeRef,
)
from src.pipeline.state_filter import STATE_UNIT_TYPES, is_pure_state_unit


def make_unit(
    summary: str,
    *,
    unit_type: str = "stock_price_change",
    evidence: list[str] | None = None,
    doc_id: str = "doc_state_filter_test",
) -> KnowledgeUnit:
    """构造最小可用 KnowledgeUnit（evidence 缺省回填 summary）。"""
    now = datetime.now(UTC)
    return KnowledgeUnit(
        unit_kind="event",
        unit_type=unit_type,
        summary=summary,
        entities=[EntityRef(mention="测试实体")],
        source=SourceRef(doc_id=doc_id, source_name="东方财富快讯"),
        evidence=[EvidenceSpan(text=text) for text in (evidence or [summary])],
        time=TimeRef(published_at=now, extracted_at=now),
    )


class TestDroppedPureStateUnits:
    """生产丢弃集真实样本：行情三类型 + 行情形态 + 无归因 + 无事件实质 → 丢弃。"""

    def test_drop_single_stock_drop(self) -> None:
        unit = make_unit("SK海力士跌超9%")
        assert is_pure_state_unit(unit) is True

    def test_drop_fx_new_low(self) -> None:
        unit = make_unit("印尼盾早盘下跌0.7%，兑美元续创历史新低")
        assert is_pure_state_unit(unit) is True

    def test_drop_index_widening_loss(self) -> None:
        unit = make_unit("日经225指数跌幅扩大至1%")
        assert is_pure_state_unit(unit) is True

    def test_drop_commodity_rise(self) -> None:
        unit = make_unit("氧化铝涨超1%")
        assert is_pure_state_unit(unit) is True

    def test_drop_limit_up_count(self) -> None:
        unit = make_unit("8月11日共计60股涨停，另有21只个股盘中触及涨停")
        assert is_pure_state_unit(unit) is True

    def test_drop_sector_breadth_decline(self) -> None:
        unit = make_unit(
            "芯片股、PCB概念普跌，澜起科技跌超6%，兆易创新跌逾5%",
            unit_type="sector_performance",
        )
        assert is_pure_state_unit(unit) is True


class TestAttributionExitKeepsUnits:
    """归因出口：行情 + 原因 → 陈述，保留。"""

    def test_keep_attribution_cause(self) -> None:
        unit = make_unit(
            "IMAX股价创新高，因电影产业迎来《奥德赛》与《蜘蛛侠：崭新之日》同档期角力的市场利好"
        )
        assert is_pure_state_unit(unit) is False

    def test_keep_attribution_driven_by(self) -> None:
        unit = make_unit(
            "工程机械ETF易方达（159138）上涨3.56%，受基建投资预期升温与出海逻辑持续兑现推动"
        )
        assert is_pure_state_unit(unit) is False


class TestEventExitKeepsUnits:
    """事件实质出口：承载事件（财报/业绩）而非行情快照 → 保留。"""

    def test_keep_earnings_word(self) -> None:
        # 任务指定样本：summary 无归因词，"业绩"命中财报组事件词
        #（该样本同时不含行情模板词，词表层面双保险）
        unit = make_unit("业绩暴雷次日股价腰斩")
        assert is_pure_state_unit(unit) is False

    def test_keep_event_word_alone_blocks_drop(self) -> None:
        # 纯事件出口验证：行情形态命中 + 无归因词 + 事件词命中 → 保留
        unit = make_unit("业绩暴雷，股价跌停")
        assert is_pure_state_unit(unit) is False

    def test_keep_net_profit_and_attribution(self) -> None:
        # "净利"命中事件词，"因"命中归因词，双出口保留
        unit = make_unit("因Q3净利超预期比亚迪涨停")
        assert is_pure_state_unit(unit) is False


class TestUnitTypeGuard:
    """类型限定：非行情三类型的 KU 不进入判定（即便形态命中）。"""

    def test_keep_financial_performance(self) -> None:
        unit = make_unit(
            "天赐材料发布2026年半年度报告，营业收入同比增长109.28%",
            unit_type="financial_performance",
        )
        assert is_pure_state_unit(unit) is False

    def test_keep_market_analysis_opinion(self) -> None:
        unit = make_unit(
            "当前市场观点：A股后市或维持震荡格局",
            unit_type="market_analysis",
        )
        assert is_pure_state_unit(unit) is False

    def test_state_types_are_the_three_quote_types(self) -> None:
        # 词表与设计文档 §2.1 保持一致，防止悄悄漂移
        assert STATE_UNIT_TYPES == {
            "stock_price_change",
            "price_change",
            "sector_performance",
        }


class TestEvidenceExit:
    """边界：summary 无归因词但 evidence 有 → 保留（出口看 summary+evidence 拼接）。"""

    def test_keep_when_attribution_only_in_evidence(self) -> None:
        unit = make_unit(
            "创业板指涨超1%",
            evidence=["创业板指涨超1%，因新能源权重股集体反弹带动市场情绪回暖"],
        )
        assert is_pure_state_unit(unit) is False

    def test_keep_when_event_word_only_in_evidence(self) -> None:
        unit = make_unit(
            "半导体板块走强",
            evidence=["半导体板块走强，消息面上某大厂财报营收超预期"],
        )
        assert is_pure_state_unit(unit) is False
