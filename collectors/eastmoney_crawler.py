#!/usr/bin/env python3
"""
东方财富 7x24快讯 爬虫
获取最新的全球财经快讯数据并存入本地数据库。
"""

import argparse
import hashlib
import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from config import EventType, SourceType
from database import Database

# 延迟初始化的日志器
_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    """获取日志器（延迟初始化）。"""
    global _logger
    if _logger is None:
        _logger = logging.getLogger(__name__)
    return _logger

# 常用 User-Agent 列表，用于随机切换防反爬
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
]

class EastMoneyCrawler:
    """东方财富快讯爬虫"""
    
    API_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    
    def __init__(self, db_path: str = "data/news.db"):
        self.db = Database(db_path)
        self.consecutive_errors = 0  # 连续错误计数器
        
    def fetch_news(self, page_size: int = 100) -> list[dict] | None:
        """抓取快讯列表。返回 None 表示抓取失败（网络错误或被拦截）。"""
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102", # 102 为7x24快讯
            "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(int(time.time() * 1000)),
        }
        
        query_string = urllib.parse.urlencode(params)
        url = f"{self.API_URL}?{query_string}"
        
        # 随机选用 User-Agent
        req = urllib.request.Request(url, headers={
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://kuaixun.eastmoney.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        
        _get_logger().info(f"Fetching news from {self.API_URL} (pageSize={page_size})")

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return data.get("data", {}).get("fastNewsList", [])
                else:
                    _get_logger().error(f"Unexpected HTTP Status: {response.status}")
                    return None
        except urllib.error.HTTPError as e:
            _get_logger().error(f"HTTP Error: {e.code} {e.reason}")
            # 常见的反爬虫状态码
            if e.code in (403, 429, 503):
                _get_logger().warning(f"🚨 警告: 检测到可能的反爬虫拦截 (状态码: {e.code})!")
            return None
        except Exception as e:
            _get_logger().error(f"Request failed: {e}")
            return None

    def _infer_category(self, text: str) -> str:
        """简单的规则推断事件类别"""
        text = text.lower()
        if any(w in text for w in ["制裁", "出口管制", "黑名单", "实体清单", "脱钩"]):
            return EventType.POLICY_SANCTION.name
        if any(w in text for w in ["并购", "收购", "重组", "合并"]):
            return EventType.CORPORATE_MERGER.name
        if any(w in text for w in ["供应链", "断供", "停产", "产能不足", "缺货"]):
            return EventType.SUPPLY_CHAIN.name
        if any(w in text for w in ["财报", "营收", "净利", "业绩预告", "年报", "季报"]):
            return EventType.FINANCIAL_EARNINGS.name
        if any(w in text for w in ["监管", "合规", "调查", "罚款", "反垄断", "违规"]):
            return EventType.REGULATORY_ACTION.name
        if any(w in text for w in ["关税", "贸易", "进出口", "双反"]):
            return EventType.TARIFF_TRADE.name
        if any(w in text for w in ["辞职", "任命", "高管变动", "CEO", "董事长"]):
            return EventType.EXECUTIVE_CHANGE.name
        if any(w in text for w in ["ipo", "上市", "融资", "增发", "募资"]):
            return EventType.IPO_FUNDING.name
        if any(w in text for w in ["地缘政治", "俄乌", "巴以", "冲突", "战争", "军演"]):
            return EventType.GEOPOLITICAL.name
            
        return EventType.MARKET_VOLATILITY.name

    def process_and_save(self, news_list: list[dict]) -> int:
        """处理并保存数据到数据库"""
        articles = []
        for item in news_list:
            # 数据清洗
            title = item.get("title", "")
            summary = item.get("summary", "")
            if item.get('code'):
                doc_id = f"em_{item.get('code')}"
            else:
                content_hash = hashlib.md5((title + summary).encode('utf-8')).hexdigest()[:16]
                doc_id = f"em_{content_hash}"
            content = summary if summary else title
            show_time = item.get("showTime", "")
            
            if not title or not show_time:
                continue
                
            category_name = self._infer_category(title + " " + summary)
            
            articles.append({
                "doc_id": doc_id,
                "title": title,
                "content": content,
                "publish_time": show_time,
                "source_name": "东方财富快讯",
                "source_type": SourceType.FINANCIAL_MEDIA.value,
                "credibility_tier": 2,
                "category": category_name,
                "raw_tags": ["快讯", "东方财富"],
            })
            
        if articles:
            inserted = self.db.insert_articles_batch(articles)
            _get_logger().info(f"Successfully inserted {inserted} out of {len(articles)} articles.")
            return inserted
        return 0

    def run(self, page_size: int = 100, continuous: bool = False, interval: int = 900):
        """运行爬虫任务"""
        log = _get_logger()
        log.info("=== 东方财富快讯爬虫启动 ===")

        while True:
            news_list = self.fetch_news(page_size=page_size)

            if news_list is not None:
                # 抓取成功，重置错误计数
                self.consecutive_errors = 0
                if news_list:
                    log.info(f"Fetched {len(news_list)} news items. Processing...")
                    self.process_and_save(news_list)
                else:
                    log.warning("Fetched successfully but no news data found.")
            else:
                # 抓取失败，增加错误计数并触发退避策略
                self.consecutive_errors += 1
                log.error(f"Failed to fetch news. Consecutive errors: {self.consecutive_errors}")

            if not continuous:
                break

            # 计算等待时间：正常间隔 + 指数退避 (在反爬虫时自动延长休眠时间)
            # 比如连续失败 1, 2, 3 次，额外等待 60, 120, 240 秒
            backoff_delay = 0
            if self.consecutive_errors > 0:
                backoff_delay = interval * (2 ** (min(self.consecutive_errors - 1, 5)))
                log.warning(f"⏱️ 触发指数退避机制，额外延迟 {backoff_delay} 秒...")

            total_sleep = interval + backoff_delay
            log.info(f"Waiting for {total_sleep} seconds before next fetch...")
            time.sleep(total_sleep)

        log.info("=== 爬虫任务完成 ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="东方财富快讯爬虫")
    parser.add_argument("--limit", type=int, default=100, help="单次抓取的快讯数量")
    parser.add_argument("--db", type=str, default="data/news.db", help="数据库路径")
    parser.add_argument("--continuous", action="store_true", help="是否持续运行")
    parser.add_argument("--interval", type=int, default=900, help="持续运行时的间隔时间(秒)")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    # 初始化日志
    from src.utils.logging import setup_logging
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    crawler = EastMoneyCrawler(db_path=args.db)
    crawler.run(page_size=args.limit, continuous=args.continuous, interval=args.interval)
