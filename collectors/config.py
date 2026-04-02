"""
数据收集器 - 配置模块

定义实体池、事件类型、新闻源等核心配置。
"""

from enum import Enum
from dataclasses import dataclass


class EventType(Enum):
    """事件类型枚举"""
    POLICY_SANCTION = "政策制裁/出口管制"
    MARKET_VOLATILITY = "股市波动/市场异动"
    CORPORATE_MERGER = "企业并购/重组"
    SUPPLY_CHAIN = "供应链中断/调整"
    FINANCIAL_EARNINGS = "财报发布/业绩预告"
    REGULATORY_ACTION = "监管处罚/合规调查"
    TARIFF_TRADE = "关税调整/贸易协定"
    EXECUTIVE_CHANGE = "高管变动/人事调整"
    IPO_FUNDING = "IPO/融资事件"
    GEOPOLITICAL = "地缘政治影响"


class SourceType(Enum):
    """信息源类型"""
    NEWS_AGENCY = "通讯社"
    GOVERNMENT = "政府公告"
    COMPANY_RELEASE = "企业公告"
    ANALYST_REPORT = "分析师报告"
    FINANCIAL_MEDIA = "财经媒体"


@dataclass(frozen=True)
class NewsSource:
    """新闻来源"""
    name: str
    source_type: SourceType
    credibility_tier: int  # 1-5, 1最高


NEWS_SOURCES: list[NewsSource] = [
    NewsSource("路透社", SourceType.NEWS_AGENCY, 1),
    NewsSource("彭博社", SourceType.NEWS_AGENCY, 1),
    NewsSource("财新网", SourceType.FINANCIAL_MEDIA, 2),
    NewsSource("华尔街日报", SourceType.FINANCIAL_MEDIA, 1),
    NewsSource("第一财经", SourceType.FINANCIAL_MEDIA, 2),
    NewsSource("中国商务部公告", SourceType.GOVERNMENT, 1),
    NewsSource("港交所公告", SourceType.COMPANY_RELEASE, 1),
    NewsSource("上证报", SourceType.FINANCIAL_MEDIA, 2),
    NewsSource("证券时报", SourceType.FINANCIAL_MEDIA, 2),
    NewsSource("36氪", SourceType.FINANCIAL_MEDIA, 3),
]

COMPANIES: list[str] = [
    "华为技术有限公司", "比亚迪股份", "宁德时代", "中芯国际",
    "腾讯控股", "阿里巴巴集团", "字节跳动", "小米集团",
    "京东集团", "百度公司", "美团", "拼多多",
    "苹果公司", "特斯拉公司", "英伟达公司", "高通公司",
    "三星电子", "台积电", "ASML控股", "英特尔公司",
    "AMD公司", "美光科技", "应用材料公司", "泛林集团",
    "中信证券", "中金公司", "高盛集团", "摩根士丹利",
    "隆基绿能", "通威股份", "天合光能", "晶澳科技",
]

GOVERNMENTS: list[str] = [
    "美国政府", "中国商务部", "欧盟委员会", "日本经济产业省",
    "韩国贸易部", "德国联邦经济部", "英国贸易部",
    "美国商务部", "美国财政部", "中国证监会", "国家发改委",
    "美国联邦贸易委员会", "欧盟竞争委员会",
]

TECHNOLOGIES: list[str] = [
    "EUV光刻机", "7nm芯片", "5nm芯片", "人工智能算力", "量子计算",
    "新能源电池", "动力电池", "自动驾驶系统", "5G通信设备", "半导体材料",
    "先进封装技术", "存储芯片", "显示面板", "碳化硅芯片",
    "GPU芯片", "AI加速器", "云计算服务", "数据中心",
]

REGIONS: list[str] = [
    "中国", "美国", "欧盟", "日本", "韩国", "台湾地区", "东南亚",
    "印度", "德国", "荷兰", "新加坡", "香港地区",
]

EVENT_TYPE_WEIGHTS: dict[EventType, int] = {
    EventType.POLICY_SANCTION: 20,
    EventType.MARKET_VOLATILITY: 15,
    EventType.CORPORATE_MERGER: 15,
    EventType.SUPPLY_CHAIN: 15,
    EventType.FINANCIAL_EARNINGS: 12,
    EventType.REGULATORY_ACTION: 10,
    EventType.TARIFF_TRADE: 8,
    EventType.EXECUTIVE_CHANGE: 3,
    EventType.IPO_FUNDING: 2,
}

GENERATION_CONFIG = {
    "total_articles": 80,
    "date_range": ("2026-01-01", "2026-03-31"),
    "batch_size": 10,
    "retry_attempts": 3,
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 2000,
    "temperature": 0.7,
}
