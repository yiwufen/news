"""Tests for state-content admission filter (``src.pipeline.state_filter``).

样本全部来自生产库实测（2026-09-30）：丢弃例取自丢弃集抽样，保留例覆盖
两类出口（归因词/事件实质词）、类型限定与 % 上下文限定。规格见
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


class TestPercentRequiresMoveContext:
    """% 上下文限定（2026-09-30 WSL 生产 dry-run 实证收紧）。

    裸 % 会误杀被 LLM 错标为 price_change 的能力/占比陈述
    （"算力消耗仅为上代产品的27%"）；% 必须与 涨/跌 相邻出现才算行情形态。
    """

    def test_keep_capability_statement_mistyped_as_price_change(self) -> None:
        # 生产 dry-run 抓到的真实误杀样本：全句无涨跌，仅"27%"为量值
        unit = make_unit(
            "DeepSeek通过架构创新实现算力消耗大幅降低，V4系列处理百万级Token长上下文时算力消耗仅为上代产品的27%",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is False

    def test_keep_share_of_total_percent(self) -> None:
        # 占比 %（非涨跌幅）：无涨跌上下文 → 不判行情形态
        unit = make_unit(
            "SpaceX购入特斯拉Cybertruck总量的8%",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is False

    def test_drop_percent_with_fall_rise_word_nearby(self) -> None:
        # "涨幅扩大至1%"：涨 与 1% 间隔 4 个非数字字符，仍在 0-6 窗口内
        unit = make_unit(
            "现货黄金日内涨幅扩大至1%，报4551.85美元/盎司",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is True

    def test_drop_percent_with_about_qualifier(self) -> None:
        # "上涨约0.5%"：涨 与 0 之间隔"约"
        unit = make_unit(
            "标普500指数期货在亚洲早盘交易中上涨约0.5%；纳斯达克100指数期货上涨0.6%",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is True

    def test_drop_crypto_rise_to_price(self) -> None:
        # 生产 dry-run 正当命中样本：涨4.53% / 涨至2125.7
        unit = make_unit(
            "以太坊过去24小时内涨4.53%，涨至2125.7美元",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is True

    def test_drop_commodity_env_rise(self) -> None:
        # 生产 dry-run 正当命中样本："环比上涨3.5%"
        unit = make_unit(
            "2026年5月中旬，焦炭（准一级冶金焦）价格为1496.4元/吨，环比上涨3.5%",
            unit_type="price_change",
        )
        assert is_pure_state_unit(unit) is True


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
