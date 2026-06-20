"""
Standard entity models, repositories, and conservative resolution helpers.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, cast
from uuid import uuid4

if TYPE_CHECKING:
    from src.retrieval.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

_DISAMBIGUATION_THRESHOLD = 0.5


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

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
    "先生",
    "女士",
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

# Precompiled single-pass suffix pattern (longest match first)
_SUFFIX_PATTERN = re.compile(
    "("
    + "|".join(re.escape(s) for s in sorted(_ENTITY_SUFFIXES, key=len, reverse=True))
    + r")$"
)

_MAX_ALIASES = 10

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
    "加沙", "加沙地带", "约旦河西岸", "红海", "红海航线",
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
    "土耳其籍船长", "日本民众", "韩国民众",
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
    # Compound abstract patterns: generic suffixes indicating non-entities
    re.compile(r".+(经济|市场|行业|政策|产业|领域|板块|概念)$"),
    re.compile(r".+(销售|生产|制造|租赁|服务|运营|管理|研发)$"),
    re.compile(r".+(行为|违规|违法|犯罪|欺诈|串标)$"),
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
    # 原油/能源大类
    "WTI原油", "布伦特原油", "油价",
    # 技术组件/材料大类
    "磷酸铁锂电池", "麒麟电池",
    # 基础设施泛指
    "算力基础设施", "数据中心",
    # 军事泛指
    "伊朗军队", "伊朗武装部队", "美军", "美方军事力量", "持久战",
    # 业务类型/泛指
    "算力租赁", "船只", "医疗器械",
    # 违规行为/动词短语
    "围标串标", "违法违规行为", "内幕交易", "操纵市场",
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

    # 单字中文不作为实体（如"以"="以色列"、"美"="美国"等缩写）
    if len(stripped) == 1 and "一" <= stripped <= "鿿":
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
    """Normalize an entity name for conservative matching.

    Multi-pass suffix stripping: repeatedly removes the longest matching corporate
    suffix until no more suffixes can be stripped (e.g. '控股股份有限公司' →
    '控股' stripped, then '股份有限公司' stripped). Always preserves at least
    one non-suffix character.
    """
    current = _strip_separators(name)
    if not current:
        return ""
    while True:
        match = _SUFFIX_PATTERN.search(current)
        if not match or match.start() == 0:
            break
        current = current[: match.start()]
    return current


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
    entity_type: EntityKind | None = None
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_ku_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# Chinese surnames (top ~200, covering >95% of Han Chinese population)
_CN_SURNAMES: frozenset[str] = frozenset({
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗",
    "郑", "梁", "谢", "宋", "唐", "许", "韩", "冯", "邓", "曹",
    "彭", "曾", "萧", "田", "董", "潘", "袁", "蔡", "蒋", "余",
    "于", "杜", "叶", "程", "苏", "魏", "吕", "丁", "任", "卢",
    "姚", "沈", "钟", "姜", "崔", "谭", "陆", "汪", "范", "金",
    "石", "廖", "贾", "夏", "韦", "付", "方", "白", "邹", "孟",
    "熊", "秦", "邱", "江", "尹", "薛", "闫", "段", "雷", "侯",
    "龙", "史", "陶", "黎", "贺", "顾", "毛", "郝", "龚", "邵",
    "万", "钱", "严", "覃", "武", "戴", "莫", "孔", "向", "汤",
    "温", "康", "施", "文", "牛", "樊", "葛", "邢", "安", "齐",
    "易", "乔", "伍", "庞", "颜", "倪", "庄", "聂", "章", "鲁",
    "岳", "翟", "殷", "詹", "申", "欧", "耿", "关", "兰", "焦",
    "俞", "左", "柳", "甘", "祝", "包", "宁", "尚", "符", "舒",
    "阮", "柯", "纪", "梅", "童", "凌", "毕", "单", "季", "裴",
    "霍", "涂", "成", "苗", "谷", "盛", "曲", "翁", "冉", "骆",
    "蓝", "路", "游", "辛", "靳", "管", "柴", "蒙", "喻", "廉",
    "解", "应", "宗", "丁", "宣", "贲", "杭", "诸", "吉", "嵇",
    "荣", "糜", "松", "井", "富", "巫", "乌", "巴", "弓", "牧",
    "牧", "山", "谷", "车", "侯", "宓", "蓬", "全", "郗", "班",
    "习", "蔚", "奚", "储", "靳", "汲", "邬", "糜", "松", "井",
})


def _infer_entity_type(name: str) -> EntityKind:
    """Infer entity type from name when the extractor provides no type.

    Only used as a fallback; the LLM extractor's entity_type is authoritative.
    Conservative by design:
    - Person requires explicit indicators (title suffix, Western name pattern)
    - Organization/Company detection relies on structural suffixes
    - Defaults to Company for ambiguous names (financial-domain prior)
    """
    # Non-entity patterns that should NOT default to Person
    _NON_PERSON_PATTERNS = re.compile(
        r"^(市场份额|股价|销售额|一季度|二季度|三季度|四季度|数据中心"
        r"|半导体|稀土|军工|生态|协议|投资|股权|在手订单|高性能计算"
        r"|台南|年度|季度|市场|行业|板块|概念|指数|基金|期货"
        r"|原油|黄金|白银|铜价|铁矿|煤炭|粮食|大豆|汇率|利率|通胀"
        r"|GDP|CPI|PMI|PPI|M2|FDI|出口|进口|贸易|顺差|逆差"
        r"|增长|下降|上升|下跌|上涨|波动|调整|变化|趋势|预期|目标"
        r"|价格|成本|收入|支出|利润|亏损|负债|资产|净值|估值"
        r"|融资|并购|重组|上市|退市|分红|回购|增发|配股|解禁)$"
    )
    if _NON_PERSON_PATTERNS.fullmatch(name):
        return "Company"

    # Organization: government/regulatory/institutional body suffixes (check first —
    # many Chinese gov names are 2-3 chars and would otherwise be ambiguous)
    if re.search(
        r"(部|委|局|院|署|会|厅|处|办|行|所|中心|总局|总署|办公室"
        r"|委员会|管理局|监管局|交易所|清算所|联合会|基金会|理事会"
        r"|协会|机构|研究院|部门|政府|联盟|银行|证券|保险|信托"
        r"|商会|法院|检察院|代表大会|办公厅|指挥部|司令部)$",
        name,
    ):
        return "Organization"

    # Person: explicit title suffix (strongest Person signal)
    if re.search(
        r"(先生|女士|总裁|董事长|CEO|创始人|总理|首相|总统|主席"
        r"|部长|局长|市长|省长|书记|教授|博士|法官|律师|司令"
        r"|将军|经理|总监|主任|秘书|发言人|代表|大使)$",
        name,
        re.IGNORECASE,
    ):
        return "Person"

    # Person: Western name pattern ("John Smith", "Elon Musk")
    if re.search(r"^[A-Z][a-z]+\s+[A-Z]", name):
        return "Person"

    # Person: 2-3 char Chinese with known surname AND no org/company suffix
    # (conservative: only when no structural suffix present)
    if re.fullmatch(r"[一-鿿]{2,3}", name) and name[0] in _CN_SURNAMES:
        return "Person"

    # Product: financial product suffixes
    if re.search(r"(产品|计划|基金|债券|ETF|指数|合约|期货|权证)$", name, re.IGNORECASE):
        return "Product"

    # Asset: physical/tangible asset suffixes
    if re.search(r"(资产|地块|厂房|专利|矿|油田|港口|码头|楼盘)$", name, re.IGNORECASE):
        return "Asset"

    return "Company"


def _resolve_entity_type(entity_type: str | None, mention: str) -> EntityKind | None:
    if entity_type and entity_type in ENTITY_KINDS:
        return cast(EntityKind, entity_type)
    return None


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
        "pdd": "拼多多",
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
        "tesla": "特斯拉",
        "tesla inc": "特斯拉",
        "tesla motors": "特斯拉",
        "imf": "国际货币基金组织",
        "international monetary fund": "国际货币基金组织",
        "oppo": "欧珀",
        "pony ma": "马化腾",
    }

    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )

    def _init_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT '',
                    primary_identifier TEXT,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name)"
            )
            self._ensure_column(connection, "entities", "normalized_name", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entities_norm_name ON entities(normalized_name)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    entity_id TEXT NOT NULL,
                    normalized_alias TEXT NOT NULL,
                    PRIMARY KEY (entity_id, normalized_alias)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entity_aliases_value ON entity_aliases(normalized_alias, entity_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_identifiers (
                    entity_id TEXT NOT NULL,
                    identifier_key TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    PRIMARY KEY (entity_id, identifier_key)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_entity_identifiers_lookup ON entity_identifiers(identifier_key, identifier_value, entity_id)"
            )
            connection.commit()

    def save_batch(self, entities: list[Entity], connection: sqlite3.Connection | None = None) -> int:
        if not entities:
            return 0
        rows = [
            (
                entity.entity_id,
                entity.canonical_name,
                entity.entity_type or "",
                next(iter(entity.identifiers.values()), None),
                entity.updated_at.isoformat(),
                json.dumps(entity.model_dump(mode="json"), ensure_ascii=False),
                normalize_entity_name(entity.canonical_name),
            )
            for entity in entities
        ]
        conn = connection or self._connect()
        own_connection = connection is None
        try:
            if own_connection:
                conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """
                INSERT INTO entities (
                    entity_id, canonical_name, entity_type, primary_identifier,
                    updated_at, payload, normalized_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    canonical_name = excluded.canonical_name,
                    entity_type = excluded.entity_type,
                    primary_identifier = excluded.primary_identifier,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload,
                    normalized_name = excluded.normalized_name
                """,
                rows,
            )
            # Maintain alias and identifier index tables
            entity_ids = [entity.entity_id for entity in entities]
            placeholders = ", ".join("?" for _ in entity_ids)
            conn.execute(
                f"DELETE FROM entity_aliases WHERE entity_id IN ({placeholders})",
                entity_ids,
            )
            conn.execute(
                f"DELETE FROM entity_identifiers WHERE entity_id IN ({placeholders})",
                entity_ids,
            )
            alias_rows: list[tuple[str, str]] = []
            ident_rows: list[tuple[str, str, str]] = []
            for entity in entities:
                norm_name = normalize_entity_name(entity.canonical_name)
                for alias in entity.aliases:
                    norm_alias = normalize_entity_name(alias)
                    if norm_alias and norm_alias != norm_name:
                        alias_rows.append((entity.entity_id, norm_alias))
                for key, value in entity.identifiers.items():
                    ident_rows.append((entity.entity_id, key, value))
            if alias_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO entity_aliases (entity_id, normalized_alias) VALUES (?, ?)",
                    alias_rows,
                )
            if ident_rows:
                conn.executemany(
                    "INSERT OR IGNORE INTO entity_identifiers (entity_id, identifier_key, identifier_value) VALUES (?, ?, ?)",
                    ident_rows,
                )
            if own_connection:
                conn.commit()
        except Exception:
            if own_connection:
                conn.rollback()
            raise
        finally:
            if own_connection:
                conn.close()
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

    def _entities_by_normalized_names(
        self, normalized_names: list[str]
    ) -> list[Entity]:
        if not normalized_names:
            return []
        placeholders = ", ".join("?" for _ in normalized_names)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM entities WHERE normalized_name IN ({placeholders})",
                normalized_names,
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def _entities_by_alias(self, normalized_alias: str) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.payload FROM entities e
                JOIN entity_aliases a ON e.entity_id = a.entity_id
                WHERE a.normalized_alias = ?
                """,
                (normalized_alias,),
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def _entities_by_identifier(
        self, key: str, value: str
    ) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.payload FROM entities e
                JOIN entity_identifiers i ON e.entity_id = i.entity_id
                WHERE i.identifier_key = ? AND i.identifier_value = ?
                """,
                (key, value),
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def _entities_by_identifier_value(self, value: str) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT e.payload FROM entities e
                JOIN entity_identifiers i ON e.entity_id = i.entity_id
                WHERE i.identifier_value = ?
                """,
                (value,),
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def _entities_by_normalized_prefix(self, q_lower: str) -> list[Entity]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM entities WHERE normalized_name LIKE ?",
                (f"%{q_lower}%",),
            ).fetchall()
        return [Entity.model_validate(json.loads(row["payload"])) for row in rows]

    def _entities_by_normalized_names_and_aliases(
        self, normalized_names: list[str]
    ) -> list[Entity]:
        if not normalized_names:
            return []
        seen_ids: set[str] = set()
        result: list[Entity] = []
        for e in self._entities_by_normalized_names(normalized_names):
            if e.entity_id not in seen_ids:
                seen_ids.add(e.entity_id)
                result.append(e)
        for norm in normalized_names:
            for e in self._entities_by_alias(norm):
                if e.entity_id not in seen_ids:
                    seen_ids.add(e.entity_id)
                    result.append(e)
        return result

    def find_by_names(self, query_names: Iterable[str]) -> list[Entity]:
        names = [name for name in query_names if name.strip()]
        if not names:
            return []

        matched: list[Entity] = []
        matched_ids: set[str] = set()

        for query_name in names:
            q_lower = query_name.strip().lower()

            # Layer 1: standard name matching via normalized_name/alias index
            layer1_match: Entity | None = None
            query_variants = list(build_entity_name_variants(query_name))
            norm_candidates = self._entities_by_normalized_names_and_aliases(
                query_variants,
            )
            for entity in norm_candidates:
                if entity.entity_id in matched_ids:
                    continue
                if entity_matches_query_name(
                    [entity.canonical_name, *entity.aliases],
                    query_name,
                ):
                    layer1_match = entity
                    break

            # Layer 2: cross-lingual alias → resolve to Chinese name → match
            chinese_name = self._CROSS_LINGUAL_ALIASES.get(q_lower)
            if chinese_name:
                chinese_variants = list(build_entity_name_variants(chinese_name))
                cross_candidates = self._entities_by_normalized_names_and_aliases(
                    chinese_variants,
                )
                for entity in cross_candidates:
                    if entity.entity_id in matched_ids:
                        continue
                    if entity_matches_query_name(
                        [entity.canonical_name, *entity.aliases],
                        chinese_name,
                    ):
                        matched.append(entity)
                        matched_ids.add(entity.entity_id)

            if layer1_match is not None:
                matched.append(layer1_match)
                matched_ids.add(layer1_match.entity_id)

            # Layer 3: identifier reverse lookup (ticker, ISIN, etc.)
            entity_by_id = self._entities_by_identifier_value(q_lower)
            for e in entity_by_id:
                if e.entity_id not in matched_ids:
                    matched.append(e)
                    matched_ids.add(e.entity_id)
                    break

            # Layer 4: containment fallback for short names (<= 3 chars)
            if layer1_match is None and len(q_lower) <= 3:
                contained = self._entities_by_normalized_prefix(q_lower)
                best_contained: Entity | None = None
                best_ku_count = -1
                for entity in contained:
                    if entity.entity_id in matched_ids:
                        continue
                    norm = normalize_entity_name(entity.canonical_name)
                    if q_lower in norm and len(norm) > len(q_lower):
                        ku_count = len(entity.source_ku_ids)
                        if ku_count > best_ku_count:
                            best_ku_count = ku_count
                            best_contained = entity
                if best_contained is not None:
                    matched.append(best_contained)
                    matched_ids.add(best_contained.entity_id)

        return matched

    def delete_by_id(self, entity_id: str, connection: sqlite3.Connection | None = None) -> bool:
        """从 entities、entity_aliases、entity_identifiers 三表删除指定实体。"""
        if connection is not None:
            cursor = connection.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))
            connection.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (entity_id,))
            connection.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (entity_id,))
            return cursor.rowcount > 0
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM entities WHERE entity_id = ?", (entity_id,))
            conn.execute("DELETE FROM entity_aliases WHERE entity_id = ?", (entity_id,))
            conn.execute("DELETE FROM entity_identifiers WHERE entity_id = ?", (entity_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_snapshot(self, entity_id: str) -> Entity | None:
        """加载单个实体，不存在返回 None。"""
        results = self.get_by_ids([entity_id])
        return results[0] if results else None


class EntityResolver:
    """Conservative entity resolution with optional embedding-based disambiguation."""

    def __init__(
        self,
        repository: EntityRepository,
        embedding_provider: EmbeddingProvider | None = None,
        description_generator: Any | None = None,
        alias_generator: Any | None = None,
    ):
        self.repository = repository
        self._embedding_provider = embedding_provider
        self._description_generator = description_generator
        self._alias_generator = alias_generator

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

        # Build inverted indexes for O(1) exact-match lookups
        name_index: dict[str, list[str]] = {}   # normalized_canonical → [entity_id, ...]
        alias_index: dict[str, list[str]] = {}   # normalized_alias → [entity_id, ...]
        for eid, e in entities_cache.items():
            nk = norm_cache[eid]
            if nk:
                name_index.setdefault(nk, []).append(eid)
            for alias in e.aliases:
                ak = normalize_entity_name(alias)
                if ak:
                    alias_index.setdefault(ak, []).append(eid)

        for unit in units:
            for entity_ref in unit.entities:
                candidates = self._find_candidates(
                    entity_ref.mention,
                    entity_ref.identifiers,
                    entities_cache,
                    norm_cache,
                    name_index,
                    alias_index,
                )
                matched = self._select_match(
                    candidates,
                    unit_summary=unit.summary,
                    unit_evidence=[e.text for e in unit.evidence],
                )
                if matched is None:
                    # Write-time dedup guard: log when we are about to create a
                    # new entity whose normalized name already exists in the
                    # index. _find_candidates consults name_index, so matched
                    # being None while name_index has the normalized form signals
                    # a cache/index gap or a resolver regression. Non-blocking —
                    # surfaces recurrence in logs without changing write semantics.
                    norm_mention = normalize_entity_name(entity_ref.mention)
                    if norm_mention and name_index.get(norm_mention):
                        logger.warning(
                            "Entity guard: creating new entity for mention %r "
                            "(normalized=%r) while %d existing entities share "
                            "that normalized_name; possible cache/index gap. "
                            "existing_ids=%s",
                            entity_ref.mention, norm_mention,
                            len(name_index[norm_mention]),
                            name_index[norm_mention][:5],
                        )
                    # Use cross-lingual Chinese name as canonical when available
                    cross_lingual_name = EntityRepository._CROSS_LINGUAL_ALIASES.get(
                        entity_ref.mention.strip().lower()
                    )
                    canonical = cross_lingual_name or entity_ref.mention
                    initial_aliases = [canonical] if cross_lingual_name else [entity_ref.mention]
                    if cross_lingual_name and entity_ref.mention not in initial_aliases:
                        initial_aliases.append(entity_ref.mention)

                    matched = Entity(
                        entity_type=_resolve_entity_type(
                            entity_ref.entity_type, entity_ref.mention
                        ),
                        canonical_name=canonical,
                        aliases=initial_aliases,
                        identifiers=dict(entity_ref.identifiers),
                        source_ku_ids=[unit.ku_id],
                        created_at=now,
                        updated_at=now,
                    )
                    entities_cache[matched.entity_id] = matched
                    nk = normalize_entity_name(matched.canonical_name)
                    norm_cache[matched.entity_id] = nk
                    if nk:
                        name_index.setdefault(nk, []).append(matched.entity_id)
                    for alias in matched.aliases:
                        ak = normalize_entity_name(alias)
                        if ak and ak != nk:
                            alias_index.setdefault(ak, []).append(matched.entity_id)
                    # Generate description for new entity
                    if self._description_generator and not matched.description:
                        try:
                            desc = self._description_generator.generate(
                                matched.canonical_name,
                                matched.entity_type or "",
                                matched.identifiers,
                                [unit.summary],
                            )
                            if desc:
                                matched.description = desc
                        except Exception as exc:
                            logger.warning(
                                "Description generation failed for '%s': %s",
                                matched.canonical_name, exc,
                            )
                    # Generate aliases for new entity
                    if self._alias_generator:
                        try:
                            generated = self._alias_generator.generate(
                                matched.canonical_name,
                                matched.entity_type or "",
                                matched.identifiers,
                            )
                            for alias in generated:
                                norm_alias = normalize_entity_name(alias)
                                if (
                                    alias not in matched.aliases
                                    and norm_alias not in {normalize_entity_name(a) for a in matched.aliases}
                                    and len(matched.aliases) < _MAX_ALIASES
                                ):
                                    matched.aliases.append(alias)
                                    if norm_alias and norm_alias != nk:
                                        alias_index.setdefault(norm_alias, []).append(matched.entity_id)
                        except Exception as exc:
                            logger.warning(
                                "Alias generation failed for '%s': %s",
                                matched.canonical_name, exc,
                            )
                else:
                    # Alias dedup: skip if normalized form already present
                    # Also skip if the mention is not a valid entity name
                    # (prevents country names etc. from becoming aliases)
                    mention_norm = normalize_entity_name(entity_ref.mention)
                    existing_norms = {normalize_entity_name(a) for a in matched.aliases}
                    if (
                        is_valid_entity_mention(entity_ref.mention)
                        and entity_ref.mention not in matched.aliases
                        and mention_norm not in existing_norms
                        and len(matched.aliases) < _MAX_ALIASES
                    ):
                        matched.aliases.append(entity_ref.mention)
                        if mention_norm:
                            alias_index.setdefault(mention_norm, []).append(
                                matched.entity_id
                            )
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

    def _select_match(
        self,
        candidates: list[Entity],
        unit_summary: str = "",
        unit_evidence: list[str] | None = None,
    ) -> Entity | None:
        """Select the best entity from candidates.

        For a single candidate, returns it directly. For multiple candidates,
        uses embedding-based disambiguation if an embedding provider is
        configured and all candidates have descriptions. Otherwise falls back
        to the first candidate (highest layer priority).
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates: attempt embedding disambiguation
        if self._embedding_provider is not None:
            result = self._disambiguate(candidates, unit_summary, unit_evidence)
            if result is not None:
                return result
            # Disambiguation inconclusive — fall through to first candidate

        return candidates[0]

    def _disambiguate(
        self,
        candidates: list[Entity],
        unit_summary: str,
        unit_evidence: list[str] | None,
    ) -> Entity | None:
        """Disambiguate among multiple candidates using embedding similarity."""
        # Build context text from KU summary + evidence
        parts = [unit_summary]
        if unit_evidence:
            parts.extend(unit_evidence)
        ku_context = " ".join(parts)

        if not ku_context.strip():
            return candidates[0]

        # Build comparison text for each candidate
        candidate_texts = [
            c.description if c.description
            else " ".join([c.canonical_name] + c.aliases[:3])
            for c in candidates
        ]

        # Compute embeddings
        all_texts = [ku_context] + candidate_texts
        try:
            embeddings = self._embedding_provider.embed(all_texts)  # type: ignore[union-attr]
        except Exception:
            logger.warning("Embedding failed during disambiguation, falling back")
            return candidates[0]

        ku_embedding = embeddings[0]

        # Find best candidate by cosine similarity
        best_idx = 0
        best_score = -1.0
        for i, candidate_embedding in enumerate(embeddings[1:]):
            score = _cosine_similarity(ku_embedding, candidate_embedding)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score >= _DISAMBIGUATION_THRESHOLD:
            logger.debug(
                "Disambiguated '%s' → '%s' (score=%.3f)",
                candidates[best_idx].canonical_name,
                candidates[best_idx].canonical_name,
                best_score,
            )
            return candidates[best_idx]

        logger.debug(
            "Disambiguation: best score %.3f below threshold %.3f, falling back to first candidate",
            best_score,
            _DISAMBIGUATION_THRESHOLD,
        )
        return None  # caller falls back to candidates[0]

    def _find_candidates(
        self,
        mention: str,
        identifiers: dict[str, str],
        entities_cache: dict[str, Entity],
        norm_cache: dict[str, str],
        name_index: dict[str, list[str]],
        alias_index: dict[str, list[str]],
    ) -> list[Entity]:
        """Return all candidate entities for a mention, ordered by layer priority."""
        normalized = normalize_entity_name(mention)
        candidates: dict[str, Entity] = {}

        # Layer 1: identifier exact match via entity_identifiers table (indexed)
        if identifiers:
            for key, value in identifiers.items():
                for entity in self.repository._entities_by_identifier(key, value):
                    if entity.entity_id not in candidates:
                        if entity.entity_id not in entities_cache:
                            entities_cache[entity.entity_id] = entity
                            nk = normalize_entity_name(entity.canonical_name)
                            norm_cache[entity.entity_id] = nk
                            if nk:
                                name_index.setdefault(nk, []).append(entity.entity_id)
                            for alias in entity.aliases:
                                ak = normalize_entity_name(alias)
                                if ak and ak != nk:
                                    alias_index.setdefault(ak, []).append(entity.entity_id)
                        candidates[entity.entity_id] = entities_cache[entity.entity_id]

        # Layer 1.5: cross-lingual alias → resolve to Chinese name → match
        cross_lingual = EntityRepository._CROSS_LINGUAL_ALIASES.get(
            mention.strip().lower()
        )
        if cross_lingual:
            cross_norm = normalize_entity_name(cross_lingual)
            for eid in name_index.get(cross_norm, []):
                if eid not in candidates:
                    candidates[eid] = entities_cache[eid]
            for eid in alias_index.get(cross_norm, []):
                if eid not in candidates:
                    candidates[eid] = entities_cache[eid]

        # Layer 2: normalized canonical name exact match via index (O(1))
        for eid in name_index.get(normalized, []):
            if eid not in candidates:
                candidates[eid] = entities_cache[eid]

        # Layer 3: normalized alias exact match via index (O(1))
        for eid in alias_index.get(normalized, []):
            if eid not in candidates:
                candidates[eid] = entities_cache[eid]

        # Layer 4: SequenceMatcher fuzzy match (no type constraint — type may be None)
        for entity in entities_cache.values():
            if entity.entity_id in candidates:
                continue
            norm_name = norm_cache[entity.entity_id]
            similarity = SequenceMatcher(None, normalized, norm_name).ratio()
            if similarity >= 0.95:
                candidates[entity.entity_id] = entity

        return list(candidates.values())
