"""状态类知识单元准入过滤（纯函数，无 IO、无第三方调用）。

设计文档：``docs/design-issues/state-vs-statement-routing.md`` §2.1。

判定一句话：一年后再读仍是真命题的是陈述（入库）；被下一笔报价取代的
是状态（不入知识层，"涨多少"由 marketdata 工具承接）。

形态法边界（本模块为什么可以用正则，以及何时不可以）：

- 词表绑定东方财富模板化快讯单一文体——中文财经快讯表达因果时几乎总用
  ``因/受/由于`` 等显式标记，缺失这些标记即可判为纯行情快照叙事；
- 本规则运行在 LLM 抽取**之后**：LLM 已读全文、已做语义分类、已按 prompt
  倾向提取有归因的内容，规则处理的是被语义预筛选的残差流，不是原始语义流。
  语义判定在 LLM 抽取层完成，本模块不做任何语义理解；
- 接入自由文本源时，``%`` 与走势词是歧义的（占比/目标值/通胀走势），届时需
  按 ``source_name`` 一行判断整体关闭（见设计文档 §2.1"词表绑定单一文体"）。

实测依据（2026-09-30，生产库全量跑精确规则）：行情类 KU 23,179 条中命中
丢弃 16,516 条（71%）；丢弃集随机抽样 15 条目测全部为纯状态，0 误杀。
误杀兜底：保守四条件 AND + 被丢 KU 可由重处理重建（一切可逆）。
"""

from __future__ import annotations

import re

from src.knowledge_base import KnowledgeUnit

# 行情三类型：只有这三个 unit_type 的 KU 才进入状态过滤判定
STATE_UNIT_TYPES = {"stock_price_change", "price_change", "sector_performance"}

# 强行情模板词（已按生产数据校准，勿改动）：
# 涨/跌+数字（含全角）、%（行情快照必带量）、涨停/跌停/连板/拉升/异动/冲高/回落…
# 注意 % 与走强/走低在原始流里是歧义的（占比/目标值/通胀走势），因此本模式
# 只在 KU 级（语义预筛选后的残差流）使用，不做文档级预过滤。
MOVE_PATTERN: re.Pattern[str] = re.compile(
    r"[涨跌][0-9０-９]|[%％]|涨停|跌停|连板|拉升|走强|走弱|走高|走低|异动|跳水|冲高|回落|反弹|翻红|翻绿|新高|新低|直线|下挫"
)

# 归因出口：命中即视为"行情 + 原因"的陈述而非纯状态（词表含"拉动"——实测首版漏了）
ATTRIBUTION_PATTERN: re.Pattern[str] = re.compile(
    r"因|受.{0,8}影响|由于|得益于|推动|带动|拉动|引发|刺激|消息面上|利好|利空|担忧|预期|影响|因为|催化"
)

# 事件实质出口：命中说明 KU 承载的是事件而非行情快照。
# 源自 collectors/eastmoney_crawler.py ``_infer_category`` 的 9 组事件关键词
# （制裁/并购/供应链/财报/监管/关税/高管/IPO/地缘），并补充股权与裁决类词。
EVENT_PATTERN: re.Pattern[str] = re.compile(
    r"制裁|出口管制|黑名单|实体清单|脱钩|并购|收购|重组|合并|供应链|断供|停产|产能|缺货|财报|营收|净利|业绩|年报|季报|监管|合规|调查|罚款|反垄断|违规|关税|贸易|进出口|双反|辞职|任命|高管变动|董事长|IPO|上市|融资|增发|募资|地缘|俄乌|巴以|冲突|战争|军演|中标|获批|判决|处罚|减持|增持|质押"
)


def is_pure_state_unit(unit: KnowledgeUnit) -> bool:
    """判断一条 KU 是否为纯状态行情快照（True = 应丢弃）。

    规则（保守 AND，出口优先，宁可漏杀不可误杀）：

    1. ``unit_type`` ∈ 行情三类型（类型限定，财报/观点等其余 29 类不进入判定）；
    2. summary 命中行情模板词（无行情形态的 KU 不判）；
    3. 拼接文本（summary + 全部 evidence.text，空格分隔防跨串误配）不命中
       归因词且不命中事件实质词——任一出口命中都保留。

    拼接判定意味着：summary 无归因但 evidence 提到原因的 KU 同样保留。
    """
    if unit.unit_type not in STATE_UNIT_TYPES:
        return False
    if not MOVE_PATTERN.search(unit.summary):
        return False
    # 归因/事件出口看 summary 与全部 evidence 的拼接文本
    combined = " ".join(
        [unit.summary, *(span.text for span in unit.evidence)]
    )
    if ATTRIBUTION_PATTERN.search(combined):
        return False
    if EVENT_PATTERN.search(combined):
        return False
    return True
