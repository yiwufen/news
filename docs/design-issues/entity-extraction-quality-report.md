# 知识单元质量问题分析报告

**日期**: 2026-05-10
**版本**: v1.0
**分析范围**: 15,908 个知识单元 / 13,441 个实体
**样本量**: 20 个随机知识单元 + 200 个关系样本

---

## 执行摘要

在对当前知识库进行抽样审查后，发现知识单元抽取存在**三个系统性质量问题**：

1. **实体类型误分类**：抽象概念被错误标注为 Person/Product
2. **关系端点缺失**：relation_hints 字段中 43-45% 的 entity_id 为 null
3. **实体粒度失控**：业务描述、抽象名词被抽取为实体

这些问题源于 **LLM 提示词设计缺陷** 和 **后置过滤机制不足** 的组合效应。

---

## 一、实体类型误分类问题

### 1.1 问题表现

随机抽样 20 个知识单元中，发现以下实体类型标注错误：

| 实体 mention | 错误标注类型 | 合理分类 | 样本ID |
|------------|------------|---------|--------|
| 全球经济 | Person | 应排除（抽象概念） | ku_5a3fe8392730f607 |
| 宏观经济政策 | Person | 应排除（抽象概念） | ku_5a3fe8392730f607 |
| 围标串标 | Product | 应排除（抽象行为） | ku_d561c18d69e33290 |
| 违法违规行为 | Product | 应排除（抽象行为） | ku_d561c18d69e33290 |
| 美伊谈判 | Organization | 应排除（事件描述） | ku_9971865539b9b30b |
| 增长 | Person | 应排除（动词/抽象） | 样本外 |

### 1.2 类型标注错误率估算

基于 20 个样本的观察（5 个明显错误），粗略估算：
- **实体级别错误率**：约 5-10% 的实体存在类型误标
- **知识单元级别错误率**：约 25% 的知识单元包含至少 1 个错误类型实体

### 1.3 影响范围

- **检索准确率下降**：用户查询"Person: 全球经济"无法匹配任何结果
- **实体归并失败**：错误类型导致同一实体无法跨文档归并（例如不同语境下同一概念被标为不同类型）
- **下游分析污染**：基于 entity_type 的统计、分析结果失真

---

## 二、关系端点缺失问题

### 2.1 问题表现

relation_hints 字段存在严重的 entity_id 缺失问题：

| 指标 | 数值 | 样本量 |
|------|------|--------|
| 有 relation_hints 的 KU 占比 | 28% | 200 |
| subject_entity_id 非空率 | 57% | 75 条关系 |
| object_entity_id 非空率 | 55% | 75 条关系 |

**典型样例**：

```json
{
  "ku_id": "ku_68bb5143d3c06684",
  "entities": [
    {"mention": "诺和诺德", "entity_id": "ent_844fffa4f7e9"},
    {"mention": "OpenAI", "entity_id": "ent_4839cd52042c"}
  ],
  "relation_hints": [
    {
      "relation_type": "合作关系",
      "subject_entity_id": null,
      "object_entity_id": null,
      "confidence": 0.8
    }
  ]
}
```

尽管该知识单元明确包含两个实体（诺和诺德、OpenAI），relation_hints 的端点仍为 null，**完全丢失了关系信息**。

### 2.2 关系类型混乱

- 中英文混杂：`袭击`、`participate`、`invest_in`、`achieved`、`尚未收到`、`变为`
- 无标准词表：同类关系使用不同表述（如"合作关系" vs "合作" vs "collaboration"）
- 无置信度分层：所有关系默认 confidence=0.8，未区分事实陈述与推断

### 2.3 影响范围

- **关系图无法构建**：43-45% 的关系端点缺失，导致知识图谱中的关系路径断裂
- **关系检索失效**：用户查询"A与B的关系"时，因端点为 null 无法返回结果
- **数据质量下降**：relation_hints 字段在近 3/4 的知识单元中为空，schema 设计形同虚设

---

## 三、实体粒度失控问题

### 3.1 问题表现

实体抽取的粒度标准不一致，存在过粗与过细现象：

| 合理实体 | 过粗实体（应排除或拆分） | 样本ID |
|---------|---------------------|--------|
| 翔宇医疗 | 第二类医疗器械销售 | ku_709eea514ba351fb |
| 华为Pura90ProMax | 第一类医疗设备租赁 | ku_709eea514ba351fb |
| 特福国际 | 围标串标 | ku_d561c18d69e33290 |
| 中汽协 | 宏观经济政策 | ku_5a3fe8392730f607 |
| 贵阳 | 自动驾驶移动空间 | ku_9a3ef9ff7ea8839c |

### 3.2 粒度问题分类

**类型 A：业务描述被当作实体**
- `第二类医疗器械销售`、`第一类医疗设备租赁`、`第一类医疗器械生产`
- 本质是企业经营范围，应拆分为：实体（公司）+ 标签（业务类型）

**类型 B：抽象名词被当作实体**
- `宏观经济政策`、`全球经济`、`新能源汽车市场`
- 无法对应到具体对象，应转为 tags 或排除

**类型 C：事件名被当作实体**
- `美伊谈判`、`奇遇环线`
- 是事件描述或项目名称，不应作为具名实体抽取

### 3.3 影响范围

- **实体库污染**：13,441 个实体中包含大量非具名对象，降低实体质量
- **检索召回率下降**：用户搜索"翔宇医疗"时，无法匹配到"第二类医疗器械销售"
- **实体归并困难**：同一业务在不同文档中被表述为不同 mention，无法识别为同一实体

---

## 四、根因分析

### 4.1 LLM 提示词缺陷

**核心缺陷 1：relation_hints 完全未提及**

当前提示词（`src/knowledge_extractor.py:23-91`）共 91 行，**没有任何内容关于 relation_hints 的抽取规范**：

- 没有"何时抽取关系"的指令
- 没有"如何从 entities 中选择 subject/object"的示例
- 没有"relation_type 标准词表"

**直接后果**：LLM 不知道要填 relation_hints 字段，或不知道如何填写，导致 43-45% 的端点为 null。

---

**核心缺陷 2：抽象概念约束采用"列举法"**

提示词第 44 行要求排除「抽象概念（如「市场」「价格」「行业」「停火」「增长」「经济增长」）」，但存在两个问题：

1. **列举不完整**：只列举了 6 个示例，无法覆盖所有变体
   - 禁了"经济增长"，漏放"全球经济""宏观经济政策"
   - 禁了"市场"，漏放"新能源汽车市场""A股市场"

2. **无判断标准**：LLM 无法从示例中归纳出"什么是抽象概念"，只能机械匹配列举词

**直接后果**：大量抽象概念变体通过抽取，被错误标注为 Person/Product。

---

**核心缺陷 3：实体类型定义模糊**

提示词第 35 行定义 Product 为「具体产品或基金名称」，但：

- "具体"的定义不清晰，LLM 可能认为"违法违规行为"也是产品类别
- 没有给出"如何判断是否具名"的标准
- 没有 mention 复杂度约束（字数、是否包含动词等）

**直接后果**：业务描述、抽象名词被当作 Product 抽取。

---

**核心缺陷 4：负约束为主，缺乏正面标准**

提示词实体抽取规范共 13 行负约束（"绝不能抽取 X"），但只有 5 行正约束（"只能抽取 Y"）：

- 负约束：数值、股票代码、价格、国家、货币、抽象概念、泛指角色、时间、财务指标、指数、代词、军事泛指
- 正约束：Company、Organization、Person、Product、Asset

**问题**：负约束无法穷举所有边界情况，LLM 在遇到未列case时倾向"多抽"（宁可错杀不可漏过）。

---

**核心缺陷 5：无抽取后自检机制**

提示词没有要求 LLM 在抽取后进行自我验证，例如：

- "检查每个 entity mention 是否满足以下条件：具名、可识别、非抽象"
- "检查 relation_hints 的 subject/object entity_id 是否在 entities 列表中"

**直接后果**：LLM 抽取的错误无法在输出前被拦截。

---

### 4.2 后置过滤机制不足

`src/entities.py:184` 的 `is_valid_entity_mention()` 函数提供三层过滤，但均存在缺陷：

#### 层级 1：精确匹配 (`_ABSTRACT_CONCEPTS`)

```python
_ABSTRACT_CONCEPTS: frozenset[str] = frozenset({
    "市场", "价格", "行业", "停火", "增长", "下降", "上涨", "下跌",
    ...
    "经济增长",  # ← 有这个
    # 但没有 "全球经济", "宏观经济政策"
})
```

**缺陷**：静态枚举，无法覆盖复合词（"全球经济" vs "经济"）。

---

#### 层级 2：正则匹配 (`_NON_ENTITY_GENERIC_PATTERNS`)

```python
_NON_ENTITY_GENERIC_PATTERNS: list[re.Pattern[str]] = [
    ...
    re.compile(r"^(经济|金融|科技|教育|医疗|军事|政治|文化|社会|体育)$"),  # ← ^...$ 要求整串完全匹配
]
```

**缺陷**：正则锚定到首尾，带前缀的词（如"全球经济"、"新能源汽车市场"）全部漏放。

---

#### 层级 3：角色词过滤 (`_GENERIC_ROLE_WORDS`)

```python
_GENERIC_ROLE_WORDS: frozenset[str] = frozenset({
    "记者", "员工", "用户", ... "分析师", "董事会"
})
```

**缺陷**：只过滤角色词，不过滤抽象概念和业务描述。

---

**综合缺陷**：三层过滤都没有处理"复合抽象词"（如"全球经济"、"宏观经济政策"）和"业务描述"（如"第二类医疗器械销售"）。

---

### 4.3 Pipeline 缺失环节

#### 环节 1：relation_hints 无回填逻辑

`src/pipeline/continuous.py` 的处理流程：

1. Stage 1: 抽取 KnowledgeUnit（LLM 输出）
2. Stage 2: 解析 entities 中的 entity_id（调用 `EntityResolver.resolve_units_with_cache`）
3. Stage 3: 事件聚类

**问题**：Stage 2 只处理 `entities` 字段，**完全不处理** `relation_hints` 字段的 subject/object entity_id。

即使 LLM 在 relation_hints 中填入了 mention（而非 entity_id），pipeline 也没有将其映射到 entity_id 的逻辑。

---

#### 环节 2：无 relation_type 标准化

Pipeline 没有对 relation_type 进行任何验证或标准化：

- 允许中英文混杂
- 允许任意自定义类型
- 无同义词合并逻辑

---

## 五、数据质量量化

### 5.1 实体质量指标

基于 20 个随机样本（共 72 个实体）：

| 指标 | 数值 | 说明 |
|------|------|------|
| 实体总数 | 72 | 20 个 KU 的 entities 列表 |
| 错误类型实体 | 5 | 类型误标或应排除 | | 错误率 | 6.9% | 样本级估算 |
| role 为 None 的实体 | 58 | 80.5% | | relation_hints 覆盖率 | 25% | 仅 5/20 个 KU 有关系 |

### 5.2 关系质量指标

基于 200 个随机样本：

| 指标 | 数值 | 样本量 |
|------|------|--------|
| 有 relation_hints 的 KU | 56 | 200 |
| relation_hints 覆盖率 | 28% | 56/200 |
| 关系总数 | 75 | - |
| subject 非空 | 43 (57%) | 75 |
| object 非空 | 41 (55%) | 75 |
| 两端都非空 | ~30 (40%) | 推算 |

### 5.3 全库外推

假设样本具有代表性，外推到全库：

- **错误类型实体数量**：约 900-1,300 个（13,441 的 6.9-10%）
- **无角色的实体数量**：约 10,800 个（80.5%）
- **可用关系数量**：约 2,000 条（估算全库约 5,000 条关系，40% 两端非空）

---

## 六、下游影响评估

### 6.1 对检索的影响

**召回率下降**：

- 用户查询"全球经济的最新数据"，因"全球经济"被标为 Person，无法匹配到相关知识单元
- 用户查询"翔宇医疗"，因文档中实体为"第二类医疗器械销售"，无法召回

**准确率下降**：

- 用户查询"Person: 特朗普"，可能召回"全球经济"（错误标注为 Person）

### 6.2 对知识图谱构建的影响

**关系路径断裂**：

- 43-45% 的关系端点为 null，导致图遍历无法完成
- 即使端点非 null，因格式不一致（如 `product_polysilicon` 而非 `ent_xxx`），无法关联到实体节点

**实体归并失败**：

- 错误的 entity_type 导致同一实体无法跨文档归并
- 例如："全球经济"在文档 A 标为 Person，在文档 B 标为 Organization，归并逻辑认为这是两个实体

### 6.3 对数据分析的影响

**实体统计失真**：

- Person 类型实体中包含"全球经济"、"宏观经济政策"，导致 Person 实体数量虚高
- Product 类型实体中包含"围标串标"、"违法违规行为"，导致产品分类不可用

**关系分析不可用**：

- 因 relation_hints 大量缺失，无法做"谁与谁有关系"的网络分析
- 关系类型不统一，无法做"合作/竞争/投资"等模式挖掘

---

## 七、优先级分级

基于影响范围和修复难度，对三个问题进行优先级分级：

| 问题 | 影响范围 | 修复难度 | 优先级 |
|------|---------|---------|--------|
| **relation_hints 端点缺失** | 高（关系检索完全失效） | 低（pipeline 补一段逻辑） | **P0** |
| **实体类型误分类** | 中（部分检索失效） | 中（提示词优化+过滤增强） | **P1** |
| **实体粒度失控** | 中（实体库污染） | 高（需要定义粒度标准） | **P2** |

---

## 八、附录

### A. 样本数据

完整样本数据见脚本输出：
```
uv run python -X utf8 -c "
import sqlite3, json
conn = sqlite3.connect('data/news.db')
cur = conn.cursor()
cur.execute('SELECT ku_id, payload FROM knowledge_units WHERE status=\"active\" ORDER BY RANDOM() LIMIT 20')
..."
```

### B. 相关文件

| 文件 | 作用 |
|------|------|
| `src/knowledge_extractor.py` | LLM 提示词定义 |
| `src/entities.py` | 实体验证函数 `is_valid_entity_mention()` |
| `src/knowledge_base.py` | KnowledgeUnit/RelationHint schema 定义 |
| `src/pipeline/continuous.py` | 抽取-解析-聚类 pipeline |

### C. 数据库 Schema

```sql
CREATE TABLE knowledge_units (
    ku_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,  -- 包含 entities, relation_hints
    ...
);

CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    ...
);
```

---

### D. 当前 LLM 提示词全文

**文件位置**: `src/knowledge_extractor.py:23-91`

**System Prompt**（共 91 行）：

```text
你是一名金融知识工程助手，负责从新闻文档中抽取可溯源的 statement-level KnowledgeUnit。

# 核心要求
1. 每个 KnowledgeUnit 表示来源中的一次明确陈述，不要把多个事件强行合并。
2. evidence 至少保留 1 条可读证据片段。
3. source.doc_id、time.published_at、time.extracted_at 必填。
4. entities 保留原始 mention，entity_id 可以为空。
5. 发现不确定或冲突信息时，不要裁决对错，只标记 conflict_status。

# 实体抽取规范（严格）
entities 只能包含以下五类具名实体：
- Company：公司、企业（如「腾讯控股」「特斯拉」）
- Organization：政府机构、国际组织、协会（如「美联储」「联合国」）
- Person：具体人名（如「特朗普」「马斯克」），不要放泛指角色（如「记者」「员工」）
- Product：具体产品或基金名称（如「iPhone 16」「恒生指数基金」）
- Asset：具体资产（如「某地块」「某专利」）

以下内容**绝不能**作为 entity mention：
- 数值、金额、百分比（如「1.03亿元」「13%」「100」）
- 股票代码（如「002695.SZ」）
- 价格、点数（如「144美元/桶」「14445点」）
- 国家、地区、省市、海峡（如「中国」「伊朗」「山东」「上海」「霍尔木兹海峡」）
- 货币名称（如「美元」「人民币」）
- 抽象概念（如「市场」「价格」「行业」「停火」「增长」「经济增长」）
- 泛指角色词（如「记者」「员工」「用户」「股东」「董事会」）
- 时间表达、季度（如「2025年」「Q4」「上半年」）
- 财务指标/术语（如「营业收入」「净利润」「A股」「现金红利」「股票」）
- 指数/ETF/合约（如「恒生指数」「标普500指数」「主力合约」）
- 代词/指代（如「我国」「本公司」「该集团」）
- 军事泛指（如「美军」「伊朗军队」）

# 实体命名规范
- 如果提示中包含「已知实体参考」，请优先使用其中的标准名称作为 entities.mention
- 只有在已知实体列表中没有匹配项时，才使用文档中的原始表述
- 这有助于保持实体命名的一致性

# unit_type 分类规范（严格）
unit_type 只能是以下类型之一，不要使用其他值：
- financial_performance: 财务业绩、财报、营收、利润
- stock_price_change: 股价变动、涨跌
- price_change: 商品/资产价格变动
- market_analysis: 市场分析、行情、趋势
- dividend: 分红、派息
- ipo: IPO、上市
- restructuring: 资产重组、并购
- investment: 投资、融资
- product_launch: 产品发布、研发
- business_strategy: 企业战略、经营范围
- company_establishment: 企业设立
- executive_change: 高管变动、实控人变动
- legal_proceeding: 诉讼、法律
- regulatory_action: 监管处罚、行政
- policy_announcement: 政策发布、变动
- sanction: 制裁、禁运
- debt_default: 债务违约
- equity_pledge: 股权质押
- risk_warning: 风险提示、警告
- economic_data: 经济数据、指标
- trade_data: 贸易数据
- sector_performance: 板块、行业表现
- diplomatic_event: 外交声明、访问
- military_action: 军事行动
- political_statement: 政治声明
- announcement: 声明、公告
- meeting: 会议
- industry_analysis: 行业分析、趋势
- other: 无法归入以上类别

如果不确定，选择最接近的类别。

# 输出要求
- 只输出一个 JSON 对象，格式为 {"knowledge_units": [...]}
- knowledge_units 可以为空列表
- unit_kind 只能是 event 或 fact
```

**User Prompt**（`build_extraction_prompt()` 函数生成）：

```text
请从下面文档中抽取 KnowledgeUnit。

## 文档信息
- doc_id: {doc_id}
- title: {title}
- source_name: {source_name}
- published_at: {published_at}

## 正文
{content}

{entity_context_section}  # 可选：已知实体参考
```

**Tool Schema**（`EXTRACTION_TOOL_SCHEMA`）：

```json
{
  "name": "extract_knowledge_units",
  "description": "从新闻文档中抽取 statement-level KnowledgeUnit 列表",
  "input_schema": {
    "type": "object",
    "properties": {
      "knowledge_units": {
        "type": "array",
        "items": <KnowledgeUnit.model_json_schema()>
      }
    },
    "required": ["knowledge_units"]
  }
}
```

---

### E. 提示词关键缺陷索引

| 缺陷 | 对应行号 | 影响 |
|------|---------|------|
| **relation_hints 完全未提及** | 全文无 | 43-45% 的关系端点为 null |
| **抽象概念列举式约束** | 第 44 行 | "全球经济"等复合词漏放 |
| **Product 定义模糊** | 第 35 行 | "违法违规行为"被标为 Product |
| **负约束为主（13 行 vs 5 行）** | 第 38-50 行 vs 31-36 行 | LLM 倾向多抽 |
| **无自检机制** | 全文无 | LLM 不自我验证抽取结果 |
| **relation_type 无标准** | 全文无 | 中英混杂、类型混乱 |
| **粒度无约束** | 全文无 | "第二类医疗器械销售"被抽为实体 |

---

**报告编写**: Claude (Sonnet 4.6)
**数据来源**: `D:\value\news\data\news.db`
**分析时间**: 2026-05-10
