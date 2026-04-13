#!/usr/bin/env python3
"""
模拟数据收集器 - 通过 LLM 生成财经新闻
"""

import argparse
import json
import logging
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from collectors.config import (
    COMPANIES, GOVERNMENTS, TECHNOLOGIES, REGIONS,
    NEWS_SOURCES, EVENT_TYPE_WEIGHTS, EventType, GENERATION_CONFIG
)
from collectors.database import Database
from src.llm import create_offline_llm_client, get_offline_max_tokens

from anthropic.types import TextBlock

# 延迟初始化的日志器
_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    """获取日志器（延迟初始化）。"""
    global _logger
    if _logger is None:
        _logger = logging.getLogger(__name__)
    return _logger

# JSON 代码块提取正则
JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```', re.IGNORECASE)

# 叙事角度选项
PERSPECTIVES = ["客观报道", "政策解读", "市场分析", "行业观察", "企业视角"]


@dataclass(frozen=True)
class GeneratedArticle:
    """生成的文章数据"""
    title: str
    content: str
    raw_tags: tuple[str, ...]


class NewsGenerator:
    """新闻数据生成器"""

    def __init__(self, db_path: str = "data/news.db"):
        self.db = Database(db_path)
        self._init_llm_client()
        self.article_counter = self.db.get_article_count() + 1

    def _init_llm_client(self):
        """初始化 LLM 客户端（使用离线处理配置）。"""
        self.client, self.model = create_offline_llm_client()
        self.max_tokens = get_offline_max_tokens()
        self.temperature = GENERATION_CONFIG["temperature"]

    def generate_entities(self, event_type: EventType) -> dict[str, str]:
        """根据事件类型生成实体组合"""
        match event_type:
            case EventType.POLICY_SANCTION | EventType.TARIFF_TRADE | EventType.REGULATORY_ACTION:
                entities = {
                    "government": random.choice(GOVERNMENTS),
                    "company": random.choice(COMPANIES),
                }
                if random.random() > 0.5:
                    entities["technology"] = random.choice(TECHNOLOGIES)
                return entities

            case EventType.CORPORATE_MERGER | EventType.IPO_FUNDING:
                company_a, company_b = random.sample(COMPANIES, 2)
                return {"company_a": company_a, "company_b": company_b}

            case EventType.SUPPLY_CHAIN:
                return {
                    "company": random.choice(COMPANIES),
                    "technology": random.choice(TECHNOLOGIES),
                    "region": random.choice(REGIONS),
                }

            case EventType.FINANCIAL_EARNINGS | EventType.EXECUTIVE_CHANGE:
                return {"company": random.choice(COMPANIES)}

            case EventType.GEOPOLITICAL:
                region_a, region_b = random.sample(REGIONS, 2)
                return {"region_a": region_a, "region_b": region_b}

            case _:  # MARKET_VOLATILITY
                return {
                    "company": random.choice(COMPANIES),
                    "region": random.choice(REGIONS),
                }

    def select_event_type(self) -> EventType:
        """按权重随机选择事件类型"""
        return random.choices(
            list(EVENT_TYPE_WEIGHTS.keys()),
            weights=list(EVENT_TYPE_WEIGHTS.values())
        )[0]

    def generate_article(self, event_type: str, entities: dict[str, str], context: dict) -> GeneratedArticle | None:
        """调用 LLM 生成单篇新闻"""
        entities_str = "、".join(f"{k}: {v}" for k, v in entities.items())
        date = context.get("date", "2026年3月")
        perspective = context.get("perspective", "客观报道")

        prompt = f"""你是一名资深财经记者，拥有20年金融新闻报道经验。请根据以下信息撰写一篇专业的财经新闻。

## 事件信息
- 事件类型：{event_type}
- 涉及实体：{entities_str}
- 发生日期：{date}
- 叙事角度：{perspective}

## 写作要求
1. **标题**（50-80字）：客观准确，包含关键信息，吸引专业读者
2. **正文**（500-1000字）：
   - 遵循倒金字塔新闻结构
   - 包含具体数据、日期、金额（如：涉及金额约15亿美元）
   - 引用匿名消息源或官方声明（如：据消息人士透露、官方公告显示）
   - 分析对市场的潜在影响
   - 语言风格：客观、专业、数据驱动
3. **标签**（3-5个）：遵循以下规则
   - 禁止冗余：若事件类型含义已涵盖该词（如"制裁"），严禁放入标签
   - 禁止上位词：禁止使用"半导体"、"电子"、"工业"、"政策"、"供应链"等泛化词
   - 禁止情感词：标签必须是中性名词，禁止"严厉"、"重大"、"严重"等主观形容词
   - 遵循 1+1+1 结构：尽量包含 1个技术/设备标签 + 1个政策/战略背景标签 + 1个细分环节标签
   - 行业黑话优先：优先提取行业公认的术语或代号

## 输出格式
请严格按以下 JSON 格式输出，不要添加任何其他内容：
```json
{{
  "title": "新闻标题",
  "content": "新闻正文内容...",
  "raw_tags": ["标签1", "标签2", "标签3"]
}}
```"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}]
            )

            for block in response.content:
                if isinstance(block, TextBlock):
                    return self._parse_response(block.text)

            _get_logger().warning("生成失败: 未找到文本内容")
            return None

        except Exception as e:
            _get_logger().error(f"生成失败: {e}")
            return None

    def _parse_response(self, content: str) -> GeneratedArticle | None:
        """解析 LLM 响应为结构化数据"""
        try:
            match = JSON_BLOCK_RE.search(content)
            json_str = match.group(1).strip() if match else content.strip()
            data = json.loads(json_str)
            return GeneratedArticle(
                title=data["title"],
                content=data["content"],
                raw_tags=tuple(data.get("raw_tags", []))
            )
        except Exception as e:
            _get_logger().error(f"解析失败: {e}")
            return None

    def generate_time_slots(self, count: int) -> list[dict]:
        """生成时间分布，模拟真实新闻热度（工作日多于周末）"""
        start = datetime.strptime(GENERATION_CONFIG["date_range"][0], "%Y-%m-%d")
        end = datetime.strptime(GENERATION_CONFIG["date_range"][1], "%Y-%m-%d")

        dates = []
        weights = []
        current = start
        while current <= end:
            dates.append(current)
            weights.append(5 if current.weekday() < 5 else 2)
            current += timedelta(days=1)

        selected = random.choices(dates, weights=weights, k=count)
        selected.sort()

        return [
            {
                "date": d.strftime("%Y年%m月%d日"),
                "datetime": f"{d.strftime('%Y-%m-%d')}T{random.randint(8, 20):02d}:{random.randint(0, 59):02d}:00Z",
                "perspective": random.choice(PERSPECTIVES)
            }
            for d in selected
        ]

    def generate_batch(self, count: int = 10) -> list[dict]:
        """生成一批新闻"""
        articles = []
        time_slots = self.generate_time_slots(count)

        for i, slot in enumerate(time_slots):
            _get_logger().info(f"正在生成第 {i+1}/{count} 篇...")

            event_type = self.select_event_type()
            entities = self.generate_entities(event_type)
            source = random.choice(NEWS_SOURCES)

            generated = self.generate_article(
                event_type=event_type.value,
                entities=entities,
                context={"date": slot["date"], "perspective": slot["perspective"]}
            )

            if generated:
                articles.append({
                    "doc_id": f"doc_{self.article_counter:04d}",
                    "title": generated.title,
                    "content": generated.content,
                    "publish_time": slot["datetime"],
                    "source_name": source.name,
                    "source_type": source.source_type.value,
                    "credibility_tier": source.credibility_tier,
                    "category": event_type.name,
                    "raw_tags": list(generated.raw_tags),
                })
                self.article_counter += 1
            else:
                _get_logger().warning("跳过: 生成失败")

        return articles

    def run(self, total_count: int = 80, batch_size: int = 10):
        """运行生成器"""
        log = _get_logger()
        log.info(f"=== 财经情报模拟数据生成器 ===")
        log.info(f"目标数量: {total_count}, 批次大小: {batch_size}")
        log.info(f"时间范围: {GENERATION_CONFIG['date_range']}")

        all_articles = []
        batches = (total_count + batch_size - 1) // batch_size

        for batch_num in range(batches):
            batch_count = min(batch_size, total_count - batch_num * batch_size)
            log.info(f"--- 批次 {batch_num + 1}/{batches} ---")

            articles = self.generate_batch(count=batch_count)
            if articles:
                inserted = self.db.insert_articles_batch(articles)
                log.info(f"已插入 {inserted} 条记录")
                all_articles.extend(articles)

        stats = self.db.get_statistics()
        log.info(f"=== 生成完成 ===")
        log.info(f"总文章数: {stats['total_articles']}")
        for cat, cnt in stats['by_category'].items():
            log.info(f"  {cat}: {cnt}")

        return all_articles


def main():
    parser = argparse.ArgumentParser(description="生成模拟财经新闻数据")
    parser.add_argument("--count", type=int, default=80, help="生成文章数量")
    parser.add_argument("--batch-size", type=int, default=10, help="每批生成数量")
    parser.add_argument("--db", type=str, default="data/news.db", help="数据库路径")
    parser.add_argument("--stats", action="store_true", help="仅显示统计信息")
    parser.add_argument("--clear", action="store_true", help="清空数据库")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    args = parser.parse_args()

    # 初始化日志
    from src.utils.logging import setup_logging
    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
    log = _get_logger()

    generator = NewsGenerator(db_path=args.db)

    if args.stats:
        stats = generator.db.get_statistics()
        log.info(f"总文章数: {stats['total_articles']}")
        log.info(f"时间范围: {stats['time_range']['start']} ~ {stats['time_range']['end']}")
        for cat, cnt in stats['by_category'].items():
            log.info(f"  {cat}: {cnt}")
        for source, cnt in stats['by_source'].items():
            log.info(f"  {source}: {cnt}")
        return

    if args.clear:
        generator.db.clear_all()
        log.info("数据库已清空")
        return

    generator.run(total_count=args.count, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
