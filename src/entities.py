"""
Standard entity models, repositories, and conservative resolution helpers.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, Field

from src.knowledge_base import KnowledgeUnit


EntityKind = Literal["Company", "Organization", "Person", "Product", "Asset"]
ENTITY_KINDS: tuple[EntityKind, ...] = (
    "Company",
    "Organization",
    "Person",
    "Product",
    "Asset",
)

_ENTITY_SUFFIXES = (
    "集团股份有限公司",
    "控股股份有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "控股有限公司",
    "有限公司",
    "集团",
    "控股",
    "公司",
    "companylimited",
    "colimited",
    "coltd",
    "limited",
    "ltd",
    "group",
    "holdings",
    "holding",
    "incorporated",
    "inc",
    "corporation",
    "corp",
)

# 应作为标签而非实体的国家/地区/货币/抽象概念
_COUNTRY_REGION_CURRENCY: frozenset[str] = frozenset({
    # 主要国家
    "中国", "美国", "俄罗斯", "伊朗", "以色列", "日本", "韩国", "英国",
    "法国", "德国", "印度", "巴西", "加拿大", "澳大利亚", "意大利",
    "西班牙", "墨西哥", "沙特阿拉伯", "阿联酋", "土耳其", "泰国",
    "越南", "印尼", "马来西亚", "新加坡", "菲律宾", "巴基斯坦",
    "朝鲜", "乌克兰", "波兰", "荷兰", "瑞士", "瑞典", "挪威",
    "芬兰", "丹麦", "比利时", "奥地利", "爱尔兰", "葡萄牙",
    "希腊", "捷克", "罗马尼亚", "匈牙利", "新西兰", "南非",
    "埃及", "尼日利亚", "肯尼亚", "阿根廷", "智利", "哥伦比亚",
    "秘鲁", "委内瑞拉", "古巴", "蒙古", "缅甸", "柬埔寨",
    "老挝", "孟加拉国", "斯里兰卡", "尼泊尔", "伊拉克", "叙利亚",
    "约旦", "黎巴嫩", "也门", "阿曼", "卡塔尔", "巴林", "科威特",
    "阿富汗", "利比亚", "苏丹", "刚果", "坦桑尼亚",
    # 常见简称
    "美方", "中方", "俄方", "伊方", "以方", "欧方", "日方", "韩方",
    "印方", "巴方", "英方", "法方", "德方", "乌方", "朝方",
    "美伊", "中美", "中俄", "中欧", "美俄", "美以",
    # 地区
    "台湾", "香港", "澳门", "中东", "欧洲", "亚洲", "非洲", "拉美",
    "东南亚", "南亚", "东亚", "中亚", "西亚", "北非", "东欧", "西欧",
    "霍尔木兹海峡", "马六甲海峡", "苏伊士运河", "巴拿马运河",
    "加沙", "加沙地带", "约旦河西岸", "红海",
    # 省/市/区
    "山东", "广东", "江苏", "浙江", "河南", "四川", "湖北", "湖南",
    "河北", "福建", "安徽", "辽宁", "陕西", "江西", "山西", "广西",
    "云南", "贵州", "甘肃", "海南", "宁夏", "青海", "西藏", "新疆",
    "内蒙古", "黑龙江", "吉林",
    "山东省", "广东省", "江苏省", "浙江省", "河南省", "四川省",
    "湖北省", "湖南省", "河北省", "福建省", "安徽省", "辽宁省",
    "陕西省", "江西省", "重庆市", "天津市", "北京市", "上海市",
    "深圳", "广州", "南京", "杭州", "成都", "武汉", "苏州", "青岛",
    "大连", "宁波", "厦门", "济南", "郑州", "长沙", "基辅", "北京",
    "上海",
    # 货币
    "美元", "欧元", "日元", "英镑", "港元", "人民币", "韩元", "卢布",
    "卢比", "泰铢", "新元", "澳元", "加元", "瑞郎",
    # 代词/指代词
    "我国", "本国", "该国", "对方", "各方", "双方", "多方", "一方",
    "己方", "我方", "你方", "他方", "本集团", "本公司", "该公司",
    "集团", "公司",
})

# 不应作为 Person 实体的泛指词/角色词
_GENERIC_ROLE_WORDS: frozenset[str] = frozenset({
    "记者", "员工", "用户", "考生", "消费者", "投资者", "客户",
    "学生", "工人", "农民", "司机", "医生", "护士", "教师",
    "总统", "最高领袖", "实控人", "董事长", "总裁", "CEO",
    "创始人", "负责人", "发言人", "代表", "官员", "分析师",
    "受伤人员", "救援人员", "遇难者", "目击者", "当事人",
    "申请人", "被告", "原告", "嫌疑人", "受害人",
    "股东", "男性", "女性", "入围城市", "中国学者", "十大机构",
    "供应商", "合作方", "竞争者", "对手", "同行", "董事会",
    "土耳其籍船长",
})

# 纯数字/金额/百分比/价格/股票代码/时间/季度/指数 的正则
_NON_ENTITY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[\d,.]+%$"),                          # 百分比: 1.38%
    re.compile(r"^[\d,.]+\s*(元|万元|亿元|美元|港元|欧元|日元|英镑|人民币|万|亿)"),  # 金额
    re.compile(r"^[\d,.]+\s*(美元|港元)/?(股|桶|盎司|吨|克|千克)?"),  # 价格
    re.compile(r"^[\d,.]+点$"),                         # 指数点数
    re.compile(r"^[\d,.]+万?股$"),                      # 股数
    re.compile(r"^\d{6}\.(SZ|SH|HK|BJ)$"),             # 股票代码
    re.compile(r"^\d+年?$"),                            # 年份
    re.compile(r"^\d+年?\s*[\d月日期]"),                 # 年月/年期/日期
    re.compile(r"^\d{1,2}月"),                          # 月份
    re.compile(r"^\d{1,2}:\d{2}$"),                     # 时间
    re.compile(r"^\d+%—?\d+%$"),                        # 比率范围
    re.compile(r"^[\d,.]+$"),                           # 纯数字
    re.compile(r"^[一二三四五六七八九十百千万亿几多数]+$"),  # 中文数字
    re.compile(r"^第[一二三四]季度$"),                    # 第X季度
    re.compile(r"^[上下]半年$"),                         # 上/下半年
    re.compile(r"^[去今明]年$"),                         # 去/今/明年
    re.compile(r"^[上本]周$"),                           # 上/本周
    re.compile(r"(指数|ETF|合约)$"),                     # 以指数/ETF/合约结尾
    re.compile(r"^[A-Za-z0-9]{1,2}$"),                  # 极短无意义: Q4, H1
    re.compile(r"ETF"),                                 # 含ETF
]

# 通用非实体模式（仅匹配完整字符串）
_NON_ENTITY_GENERIC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(翻倍|破发|退市|停牌|复牌|涨停|跌停|熔断)$"),
    re.compile(r"^(冲突|战争|战斗|交火|打击|袭击|攻击|入侵|轰炸)$"),
    re.compile(r"^(封锁|制裁|禁运|抵制|抗议)$"),
    re.compile(r"^(增长|下降|上涨|下跌|暴跌|暴涨|大涨|大跌|回调|反弹)$"),
    re.compile(r"^(采访|谈判|对话|协商|会谈|会议|交流)$"),
    re.compile(r"^(经验|能力|技术|策略|政策|措施|方案|计划|改革)$"),
    re.compile(r"^(经济|金融|科技|教育|医疗|军事|政治|文化|社会|体育)$"),
]

# 应排除的抽象概念/通用名词/财务指标
_ABSTRACT_CONCEPTS: frozenset[str] = frozenset({
    "市场", "价格", "行业", "停火", "增长", "下降", "上涨", "下跌",
    "通胀", "通缩", "衰退", "复苏", "制裁", "关税", "加息", "降息",
    "全球", "全国", "世界", "国内", "国外", "海外",
    "同比", "环比", "同比增长", "环比增长",
    # 财务指标
    "营业收入", "净利润", "归属于上市公司股东的净利润", "现金红利", "股票",
    "营收", "利润", "分红", "股息", "市值", "估值", "市盈率",
    "成交量", "成交额", "涨幅", "跌幅", "振幅", "换手率",
    "流通市值", "总市值", "收盘价", "开盘价", "最高价", "最低价",
    "均价", "出厂价", "批发价", "零售价", "期货", "现货", "结算价",
    "毛利率", "综合毛利率", "总资产", "净资产", "负债率", "社会消费品零售总额",
    "全国房地产开发投资",
    # 通用商品/大类/指数简称
    "人工智能", "新能源", "沥青", "玉米", "主力合约", "新房",
    "经济增长", "重点企业",
    "A股", "深成指", "现货白银", "现货黄金", "现货",
    # 军事泛指
    "伊朗军队", "伊朗武装部队", "美军", "美方军事力量", "持久战",
    # 业务类型/泛指
    "算力租赁", "船只",
    # 政策/计划泛指
    "强基计划",
})


def is_valid_entity_mention(mention: str) -> bool:
    """Check if a mention is a valid entity name (not a number/amount/abstract concept)."""
    stripped = mention.strip()
    if not stripped:
        return False

    if stripped in _COUNTRY_REGION_CURRENCY:
        return False
    if stripped in _GENERIC_ROLE_WORDS:
        return False
    if stripped in _ABSTRACT_CONCEPTS:
        return False

    for pattern in _NON_ENTITY_PATTERNS:
        if pattern.search(stripped):
            return False

    for pattern in _NON_ENTITY_GENERIC_PATTERNS:
        if pattern.search(stripped):
            return False

    return True


def _strip_separators(value: str) -> str:
    return "".join(
        char
        for char in value.strip().lower()
        if unicodedata.category(char)[0] not in {"P", "Z"}
    )


def normalize_entity_name(name: str) -> str:
    """Normalize an entity name for conservative matching."""
    normalized = _strip_separators(name)
    if not normalized:
        return ""

    changed = True
    while changed and normalized:
        changed = False
        for suffix in _ENTITY_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
    return normalized


def build_entity_name_variants(*names: str) -> set[str]:
    """Build normalized name variants from canonical names and aliases."""
    variants: set[str] = set()
    for name in names:
        if not name:
            continue
        stripped = name.strip()
        if stripped:
            variants.add(stripped.lower())
        normalized = normalize_entity_name(name)
        if normalized:
            variants.add(normalized)
    return variants


def entity_matches_query_name(entity_names: Iterable[str], query_name: str) -> bool:
    """Check whether one query entity matches any canonical/alias variant."""
    query_variants = build_entity_name_variants(query_name)
    if not query_variants:
        return False

    entity_variants = build_entity_name_variants(*entity_names)
    return bool(query_variants & entity_variants)


def entity_name_in_text(entity_names: Iterable[str], text: str) -> bool:
    """Check whether a normalized entity name appears inside a longer query string."""
    text_variants = build_entity_name_variants(text)
    if not text_variants:
        return False

    entity_variants = build_entity_name_variants(*entity_names)
    for text_variant in text_variants:
        for entity_variant in entity_variants:
            if len(entity_variant) < 2:
                continue
            if entity_variant in text_variant:
                return True
    return False


class Entity(BaseModel):
    """Normalized entity."""

    entity_id: str = Field(default_factory=lambda: f"ent_{uuid4().hex[:12]}")
    entity_type: EntityKind
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_ku_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def _infer_entity_type(name: str) -> EntityKind:
    # Person: 2-4字纯汉字（常见中文姓名长度）或带称谓后缀
    if re.search(r"(先生|女士|总裁|董事长|CEO|创始人)$", name, re.IGNORECASE):
        return "Person"
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
        return "Person"
    if re.search(r"^[A-Z][a-z]+\s+[A-Z]", name):
        return "Person"
    if re.search(r"(产品|计划|基金|债券)$", name, re.IGNORECASE):
        return "Product"
    if re.search(r"(资产|地块|厂房|专利)$", name, re.IGNORECASE):
        return "Asset"
    if re.search(r"(协会|机构|研究院|部门|政府|委员会|联盟|银行|证券|基金公司)$", name):
        return "Organization"
    return "Company"


def _resolve_entity_type(entity_type: str | None, mention: str) -> EntityKind:
    candidate = entity_type or _infer_entity_type(mention)
    if candidate in ENTITY_KINDS:
        return cast(EntityKind, candidate)
    return _infer_entity_type(mention)


class EntityRepository:
    """SQLite repository for normalized entities."""

    # Cross-lingual aliases: English name (lowercase) → canonical Chinese name
    _CROSS_LINGUAL_ALIASES: dict[str, str] = {
        "byd": "比亚迪",
        "byd company": "比亚迪",
        "catl": "宁德时代",
        "xiaomi": "小米集团",
        "tencent": "腾讯控股",
        "alibaba": "阿里巴巴",
        "alibaba group": "阿里巴巴",
        "geely": "吉利汽车",
        "nio": "蔚来",
        "xpeng": "小鹏汽车",
        "xpeng motors": "小鹏汽车",
        "li auto": "理想汽车",
        "baidu": "百度",
        "jd.com": "京东",
        "jd": "京东",
        "pinduoduo": "拼多多",
        "didi": "滴滴",
        "huawei": "华为",
        "zte": "中兴通讯",
        "smic": "中芯国际",
        "hsr": "中国中车",
        "evergrande": "恒大集团",
        "china evergrande": "恒大集团",
        "country garden": "碧桂园",
        "byd electronic": "比亚迪电子",
        "suning": "苏宁",
        "midea": "美的集团",
        "gree": "格力电器",
        "haier": "海尔智家",
        "foxconn": "富士康",
        "tsmc": "台积电",
        "samsung": "三星",
    }

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    primary_identifier TEXT,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name)"
            )
            connection.commit()

    def save_batch(self, entities: list[Entity]) -> int:
        if not entities:
            return 0
        rows = [
            (
                entity.entity_id,
                entity.canonical_name,
                entity.entity_type,
                next(iter(entity.identifiers.values()), None),
                entity.updated_at.isoformat(),
                json.dumps(entity.model_dump(mode="json"), ensure_ascii=False),
            )
            for entity in entities
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO entities (
                    entity_id, canonical_name, entity_type, primary_identifier, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    entity_type = excluded.entity_type,
                    primary_identifier = excluded.primary_identifier,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                rows,
            )
            connection.commit()
        return len(entities)

    def get_all(self) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM entities ORDER BY updated_at DESC, entity_id ASC"
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def get_by_ids(self, entity_ids: Iterable[str]) -> list[Entity]:
        ids = list(dict.fromkeys(entity_ids))
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM entities WHERE entity_id IN ({placeholders})",
                ids,
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def find_by_names(self, query_names: Iterable[str]) -> list[Entity]:
        names = [name for name in query_names if name.strip()]
        if not names:
            return []
        candidates = self.get_all()

        # Pre-build identifier reverse lookup: identifier_value → entity
        identifier_lookup: dict[str, Entity] = {}
        for entity in candidates:
            for value in entity.identifiers.values():
                identifier_lookup[value.lower()] = entity

        matched: list[Entity] = []
        matched_ids: set[str] = set()

        for query_name in names:
            q_lower = query_name.strip().lower()

            # Layer 1: standard name matching (unchanged behavior)
            for entity in candidates:
                if entity.entity_id in matched_ids:
                    continue
                if entity_matches_query_name(
                    [entity.canonical_name, *entity.aliases],
                    query_name,
                ):
                    matched.append(entity)
                    matched_ids.add(entity.entity_id)

            # Layer 2: cross-lingual alias → resolve to Chinese name → match again
            chinese_name = self._CROSS_LINGUAL_ALIASES.get(q_lower)
            if chinese_name:
                for entity in candidates:
                    if entity.entity_id in matched_ids:
                        continue
                    if entity_matches_query_name(
                        [entity.canonical_name, *entity.aliases],
                        chinese_name,
                    ):
                        matched.append(entity)
                        matched_ids.add(entity.entity_id)

            # Layer 3: identifier reverse lookup (ticker, ISIN, etc.)
            entity_by_id = identifier_lookup.get(q_lower)
            if entity_by_id and entity_by_id.entity_id not in matched_ids:
                matched.append(entity_by_id)
                matched_ids.add(entity_by_id.entity_id)

        return matched


class EntityResolver:
    """Conservative entity resolution."""

    def __init__(self, repository: EntityRepository):
        self.repository = repository

    def resolve_units(
        self,
        units: list[KnowledgeUnit],
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[Entity]]:
        entities_cache = {e.entity_id: e for e in self.repository.get_all()}
        return self.resolve_units_with_cache(units, entities_cache, persist)

    def resolve_units_with_cache(
        self,
        units: list[KnowledgeUnit],
        entities_cache: dict[str, Entity],
        persist: bool = True,
    ) -> tuple[list[KnowledgeUnit], list[Entity]]:
        """
        Resolve entities using an external cache.

        Used for batch processing where multiple documents share entity context,
        avoiding redundant database loads between documents.
        """
        now = datetime.now(UTC)
        touched_entities: dict[str, Entity] = {}

        # Pre-compute normalized names to avoid repeated normalization per mention
        norm_cache: dict[str, str] = {
            eid: normalize_entity_name(e.canonical_name)
            for eid, e in entities_cache.items()
        }

        for unit in units:
            for entity_ref in unit.entities:
                matched = self._find_match(
                    entity_ref.mention,
                    entity_ref.identifiers,
                    entities_cache,
                    norm_cache,
                )
                if matched is None:
                    matched = Entity(
                        entity_type=_resolve_entity_type(
                            entity_ref.entity_type, entity_ref.mention
                        ),
                        canonical_name=entity_ref.mention,
                        aliases=[entity_ref.mention],
                        identifiers=dict(entity_ref.identifiers),
                        source_ku_ids=[unit.ku_id],
                        created_at=now,
                        updated_at=now,
                    )
                    entities_cache[matched.entity_id] = matched
                    norm_cache[matched.entity_id] = normalize_entity_name(matched.canonical_name)
                else:
                    if entity_ref.mention not in matched.aliases:
                        matched.aliases.append(entity_ref.mention)
                    if unit.ku_id not in matched.source_ku_ids:
                        matched.source_ku_ids.append(unit.ku_id)
                    matched.identifiers.update(entity_ref.identifiers)
                    matched.updated_at = now
                entity_ref.entity_id = matched.entity_id
                entity_ref.entity_type = matched.entity_type
                touched_entities[matched.entity_id] = matched

        resolved_entities = list(touched_entities.values())
        if persist:
            self.repository.save_batch(resolved_entities)
        return units, resolved_entities

    def _find_match(
        self,
        mention: str,
        identifiers: dict[str, str],
        entities_cache: dict[str, Entity],
        norm_cache: dict[str, str],
    ) -> Entity | None:
        normalized = normalize_entity_name(mention)
        inferred_type = _infer_entity_type(mention)
        for entity in entities_cache.values():
            if identifiers and entity.identifiers:
                for key, value in identifiers.items():
                    if entity.identifiers.get(key) == value:
                        return entity

            norm_name = norm_cache[entity.entity_id]
            if normalized == norm_name:
                return entity

            alias_match = next(
                (
                    alias
                    for alias in entity.aliases
                    if normalize_entity_name(alias) == normalized
                ),
                None,
            )
            if alias_match:
                return entity

            similarity = SequenceMatcher(
                None,
                normalized,
                norm_name,
            ).ratio()
            if similarity >= 0.95 and entity.entity_type == inferred_type:
                return entity
        return None
