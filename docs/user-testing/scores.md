# Retrieval Quality Scores

> 每次 search 命令后的 4 维评分记录。
> 评分标准见 `.claude/agents/user-tester.md` 中的 Retrieval Quality Scoring 段落。
> 每条记录格式：`Q<YYYYMMDD>-<NNN>`

---

<!-- 在此行下方追加新评分记录 -->

## Q20260520-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S001 |
| **Query** | `knowledge-cli search --entities "小米集团"` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 60 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 3 |
| **Overall** | 3.5 |

### Scoring Rationale
- **Relevance**: 4 — 多数结果与小米集团高度相关（股价、法务、产品、辟谣等），KU16 "小雨智造" 与小米无关但不严重
- **Info Density**: 3 — KU 包含实体、金额、时间等要素，但部分 KU 过于简略（如"小米米粉俱乐部是面向用户建立的组织"信息量低）
- **Redundancy**: 4 — 20 个唯一 cluster/20 条 KU，无重复事件占满 top-K 问题
- **Temporal**: 3 — event_time 缺失率 25%（5/20），比之前 54% 显著改善但仍有缺失

### Top 3 Results Summary
1. ku_f5868c0f8b8f257f: 小米集团股价下跌超过3% (event_time: 2026-04-09)
2. ku_363e499517c66118: 小米集团涨1.44% (event_time: None)
3. ku_e6fd9ace2076c7d6: 雷军介绍小米业务布局 (event_time: 2026-04-13)

---

## Q20260520-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S006 |
| **Query** | `knowledge-cli search --entities "BYD" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 64 |
| **Relevance** | 5 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 3 |
| **Overall** | 3.8 |

### Scoring Rationale
- **Relevance**: 5 — 英文别名 BYD 正确解析到比亚迪，Top 3 全部与比亚迪高度相关（神州租车合作、肯德基合作、商标注册）
- **Info Density**: 3 — 信息密度一般，缺少具体金额和时间细节
- **Redundancy**: 4 — 结果覆盖多个维度（战略合作、商标、产品），无明显重复
- **Temporal**: 3 — 部分缺失 event_time，但比之前测试改善

### Top 3 Results Summary
1. KU1: 比亚迪与神州租车在深圳签署闪充中国战略合作暨10万台采购框架协议
2. KU2: 比亚迪与肯德基在深圳签署战略合作协议
3. KU3: 比亚迪成功注册'比亚迪闪充'商标

---

## Q20260520-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S013 |
| **Query** | `knowledge-cli search --entities "光刻" --intent TOPIC_RESEARCH` |
| **Intent** | TOPIC_RESEARCH |
| **Result Count** | 60 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 2 |
| **Overall** | 3.3 |

### Scoring Rationale
- **Relevance**: 4 — Top 2 高度相关（光刻机概念股、光刻胶制备），KU3 优刻得与光刻无关但总体好
- **Info Density**: 3 — 结果包含股票名、技术突破等要素，但部分缺少时间
- **Redundancy**: 4 — 不同角度覆盖，无明显重复
- **Temporal**: 2 — 时间信息不够丰富，event_time 缺失

### Top 3 Results Summary
1. KU1: 光刻机概念股盘中异动，海立股份涨停，波长光电等冲高
2. KU2: 上海AI实验室攻克芯片核心材料光刻胶稳定制备难题
3. KU3: 优刻得通过工信部审核（无关）

---

## Q20260520-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S013 |
| **Query** | `knowledge-cli search --entities "量化交易" --intent TOPIC_RESEARCH` |
| **Intent** | TOPIC_RESEARCH |
| **Result Count** | 60 |
| **Relevance** | 2 |
| **Info Density** | 2 |
| **Redundancy** | 3 |
| **Temporal** | 2 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 2 — 仅 4/20 (20%) 真正与量化交易相关，多数结果匹配"交易"token（沃什交易、关联交易、期货交易等），严重偏题
- **Info Density**: 2 — 相关结果（如韩国熔断程序化交易）信息密度尚可，但 80% 无关结果稀释价值
- **Redundancy**: 3 — 无明显重复事件，但大量不相关结果间也无法判断冗余
- **Temporal**: 2 — 时间信息不够丰富，部分缺失

### Top 3 Results Summary
1. KU1: 油价推升通胀风险，'沃什交易'在美债市场退潮 (无关)
2. KU2: 东睦股份购买土地使用权项目不构成关联交易 (无关)
3. KU3: 韩国KOSPI 200指数期货上涨5%，触发熔断机制，程序化交易暂停5分钟 (相关)

---

## Q20260520-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S007 |
| **Query** | `knowledge-cli search --entities "小米集团" --time-range "2026-04-01:2026-04-30"` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 47 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 5 |
| **Overall** | 4.0 |

### Scoring Rationale
- **Relevance**: 4 — 时间过滤生效后结果更加聚焦，多数与小米相关
- **Info Density**: 3 — 与无范围搜索相同的信息密度特征
- **Redundancy**: 4 — 多样性良好
- **Temporal**: 5 — 时间范围过滤精确生效，所有 13 条有日期的 KU 均在 2026-04 范围内，无越界

### Top 3 Results Summary
1. ku_f5868c0f8b8f257f: 小米集团股价下跌超过3% (2026-04-09, in range ✅)
2. ku_363e499517c66118: 小米集团涨1.44% (None)
3. ku_e6fd9ace2076c7d6: 雷军介绍小米业务布局 (2026-04-13, in range ✅)

---

## Q20260520-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-20 |
| **Session** | ut-casual-20260520-143848 |
| **Scenario** | S013 (ad-hoc) |
| **Query** | `knowledge-cli search --entities "海思" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 60 |
| **Relevance** | 1 |
| **Info Density** | 2 |
| **Redundancy** | 2 |
| **Temporal** | 2 |
| **Overall** | 1.8 |

### Scoring Rationale
- **Relevance**: 1 — 0/20 条与华为海思半导体真正相关，全部为 BM25 短 token 碰撞噪声（海思科药企、海信等）
- **Info Density**: 2 — 海思科相关 KU 有完整信息，但与用户意图完全不符
- **Redundancy**: 2 — 海思科多条重复出现
- **Temporal**: 2 — 时间信息一般

### Top 3 Results Summary
1. KU1: 高新兴车载前装车规模组产品与海思合作 (可能相关但不确定)
2. KU2: 海思科连发三份重磅公告 (海思科药企, 无关)
3. KU3: 海思科一季度净利润超过去年全年 (海思科药企, 无关)

## Q20260510-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Query** | `knowledge-cli search --entities "英伟达" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 77 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 2 |
| **Overall** | 3.0 |

### Scoring Rationale
- **Relevance**: 4 — 多数结果与英伟达高度相关（投资、合作伙伴、产品），KU1和KU2来自同一新闻源略降低独特性
- **Info Density**: 3 — KU 包含实体、金额、时间等要素，但"英伟达投资覆盖上市公司"等过于简略
- **Redundancy**: 3 — KU1和KU2描述同一事件（英伟达400亿投资），约占10%重复；其余多样性尚可
- **Temporal**: 2 — KU1-4有event_time(2026-05-09)，但KU5等event_time=None；台积电top3全部为None

### Top 3 Results Summary
1. ku_701566ec: 英伟达投资覆盖上市公司和私营企业 (investment_scope)
2. ku_11b91d46: 英伟达2026年股权投资已突破400亿美元 (financial)
3. ku_f0465f95: 英伟达与康宁达成投资协议，承诺投资32亿美元 (investment)

---

## Q20260510-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Query** | `knowledge-cli search --entities "台积电" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 63 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 1 |
| **Overall** | 3.0 |

### Scoring Rationale
- **Relevance**: 4 — Top KUs 直接相关（股价、3纳米工厂、AI需求），偶有噪声
- **Info Density**: 3 — 包含关键信息（3纳米、2万亿美元市值），但部分KU过于简略
- **Redundancy**: 4 — 无明显重复，不同KU覆盖不同方面
- **Temporal**: 1 — Top 3 KU全部event_time=None，时间信息严重缺失

### Top 3 Results Summary
1. ku_xxx: 台积电美股夜盘涨近2% (event_time=None)
2. ku_xxx: 台积电美股盘前再涨1.6%，总市值势将再次突破2万亿美元 (event_time=None)
3. ku_xxx: 台积电在台南新增3纳米工厂 (event_time=None)

---

## Q20260510-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Query** | `knowledge-cli search --entities "海思" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 54 |
| **Relevance** | 1 |
| **Info Density** | 1 |
| **Redundancy** | 1 |
| **Temporal** | 2 |
| **Overall** | 1.3 |

### Scoring Rationale
- **Relevance**: 1 — 20条KU中0条与华为海思相关。全部为BM25短词碰撞噪声（海思科、蓝思科技、海信等）
- **Info Density**: 1 — 返回的KU虽然包含信息，但全部是关于错误实体的信息
- **Redundancy**: 1 — 多条KU描述蓝思科技（KU1, KU4, KU7, KU18），同一不相关实体占多个位置
- **Temporal**: 2 — 部分KU有event_time，但因全部无关而失去意义

### Top 3 Results Summary
1. ku_xxx: 蓝思科技H股跌超19% (完全无关)
2. ku_xxx: 海思科创新药HSK47388片新增适应症获临床试验批准 (名称碰撞)
3. ku_xxx: 广州慧仑智行科技有限责任公司成立 (完全无关)

---

## Q20260510-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | S007 |
| **Query** | `knowledge-cli search --entities "英伟达" --time-range "2026-01-01:2026-01-31"` |
| **Intent** | ENTITY_OVERVIEW (with time filter) |
| **Result Count** | 52 |
| **Relevance** | 1 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.0 |

### Scoring Rationale
- **Relevance**: 1 — 请求2026年1月数据，返回4-5月数据。时间过滤完全无效，结果与查询意图严重不符
- **Info Density**: 3 — KU本身包含完整信息，但非用户请求的时间段
- **Redundancy**: 3 — 与无时间过滤的查询结果几乎相同
- **Temporal**: 1 — 时间范围过滤完全未生效，反向范围和零长度范围也无错误提示

### Top 3 Results Summary
1. ku_xxx: 英伟达投资覆盖上市公司和私营企业 (不在2026-01范围内)
2. ku_xxx: 英伟达2026年股权投资已突破400亿美元 (不在2026-01范围内)
3. ku_xxx: 英伟达与康宁达成投资协议 (不在2026-01范围内)

---

## Q20260510-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Query** | `knowledge-cli search --entities "芯片制裁" --intent TOPIC_RESEARCH` |
| **Intent** | TOPIC_RESEARCH |
| **Result Count** | 0 |
| **Relevance** | 1 |
| **Info Density** | 1 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 1.0 |

### Scoring Rationale
- **Relevance**: 1 — 0结果，无法评估
- **Info Density**: 1 — 0结果
- **Redundancy**: 1 — 0结果
- **Temporal**: 1 — 0结果，且bm25_count=0说明FTS5完全无法匹配此短语

### Top 3 Results Summary
(无结果)

---

## Q20260510-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-10 |
| **Session** | ut-casual-20260510-002317 |
| **Scenario** | ad-hoc (芯片行业探索) |
| **Query** | `knowledge-cli search --entities "英伟达" "台积电" --intent COMPARATIVE_ANALYSIS` |
| **Intent** | COMPARATIVE_ANALYSIS |
| **Result Count** | 71 |
| **Relevance** | 3 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 2 |
| **Overall** | 2.8 |

### Scoring Rationale
- **Relevance**: 3 — 两个实体都有覆盖（英伟达12/20，台积电8/20），但无KU同时提及两个实体，缺少真正的对比分析内容
- **Info Density**: 3 — 各KU信息量适中，但缺少两实体间的关联信息
- **Redundancy**: 3 — 无严重重复，但英伟达投资类KU出现多次
- **Temporal**: 2 — 部分event_time=None，无法构建完整时间线

### Top 3 Results Summary
1. ku_xxx: 台积电CoPoS中试生产线已于2月份开始向研发团队交付设备
2. ku_xxx: SK海力士是英伟达的供货商
3. ku_xxx: 英伟达与康宁达成投资协议，承诺投资32亿美元

---

## Q20260511-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | S002 |
| **Query** | `knowledge-cli search --entities "宁德时代" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 158 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 4 — 多数 KU 与宁德时代直接相关（公司成立、超级科技日、财务数据），但实体解析带来的结果范围广
- **Info Density**: 3 — 包含金额（207.38亿净利润）、具体日期（4月21日）等要素，但部分 KU 过于简略
- **Redundancy**: 1 — Top 10 中 8 条关于"超级科技日"，同一事件占 80% 的 top-K 位置，严重降低信息多样性
- **Temporal**: 1 — 20/20 event_time 为 None (100%)，时间信息完全不可用

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司 (company_establishment)
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股 (market_analysis)
3. ku_edb195bf4935ce09: 宁德时代举办超级科技日活动 (other)

---

## Q20260511-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | S002 |
| **Query** | `knowledge-cli search --entities "宁德时代" --intent ENTITY_TIMELINE --time-range 2025-01-01:2026-05-11` |
| **Intent** | ENTITY_TIMELINE |
| **Result Count** | 100 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 4 — KU 内容与宁德时代直接相关
- **Info Density**: 3 — 包含 Q1 财务数据（净利润207.38亿），超级科技日产品信息
- **Redundancy**: 1 — 12 条 KU 中 6 条关于超级科技日（50%），且时间线维度因 event_time=None 而完全丧失
- **Temporal**: 1 — 12/12 event_time=None，时间范围参数虽记录但无法生效。时间线查询名存实亡

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司 (time=None)
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股 (time=None)
3. ku_1a81df3855b54b4c: 宁德时代将于4月21日举办2026年'超级科技日'，主题为'极域之约' (time=None)

---

## Q20260511-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | S007 |
| **Query** | `knowledge-cli search --entities "宁德时代" --time-range "2026-01-01:2026-01-31"` |
| **Intent** | ENTITY_OVERVIEW (with time filter) |
| **Result Count** | 61 |
| **Relevance** | 2 |
| **Info Density** | 3 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 1.8 |

### Scoring Rationale
- **Relevance**: 2 — 请求 2026 年 1 月数据，返回的 KU 与无时间过滤完全相同（超级科技日是 4 月事件）
- **Info Density**: 3 — KU 本身包含完整信息，但非请求的时间段
- **Redundancy**: 1 — 与 Q20260511-001 完全相同的结果
- **Temporal**: 1 — 时间范围过滤部分影响 total_count（158→61）但对返回 KU 无效，因为所有 event_time=None

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司 (不在2026-01范围内)
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股 (不在2026-01范围内)
3. ku_xxx: 星环聚能等商业核聚变公司在2026年初获得大量投资 (不在2026-01范围内)

---

## Q20260511-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | ad-hoc (CATL alias) |
| **Query** | `knowledge-cli search --entities "CATL" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 160 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 4 — CATL 英文别名正确解析到宁德时代实体，结果与中文搜索一致
- **Info Density**: 3 — 同 Q20260511-001
- **Redundancy**: 1 — 同 Q20260511-001（超级科技日占 80%）
- **Temporal**: 1 — 同 Q20260511-001（100% event_time=None）

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股
3. ku_edb195bf4935ce09: 宁德时代举办超级科技日活动

---

## Q20260511-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | ad-hoc (宁德 short name) |
| **Query** | `knowledge-cli search --entities "宁德" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 61 |
| **Relevance** | 2 |
| **Info Density** | 2 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.0 |

### Scoring Rationale
- **Relevance**: 2 — "宁德"解析到独立实体(ent_8cbb8b13b38c, canonical_name="宁德")而非宁德时代，仅 2/20 KU 提及宁德时代
- **Info Density**: 2 — 混合了宁德时代信息和无关信息（"宁组合"、"宁波"等）
- **Redundancy**: 3 — 超级科技日重复仍存在但比例降低（因总量减少）
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. ku_xxx: 宁德创历史新高 (可能是宁德时代股票简称)
2. ku_xxx: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
3. ku_xxx: 中际旭创取代宁德时代成为主动权益基金第一大重仓股

---

## Q20260511-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | ad-hoc (comparison) |
| **Query** | `knowledge-cli search --entities "宁德时代" "比亚迪" --intent COMPARATIVE_ANALYSIS` |
| **Intent** | COMPARATIVE_ANALYSIS |
| **Result Count** | 83 |
| **Relevance** | 3 |
| **Info Density** | 3 |
| **Redundancy** | 2 |
| **Temporal** | 1 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 3 — 两个实体都有覆盖（宁德时代 15/20, 比亚迪 5/20），比之前(20:0)大幅改善，但仍无 KU 同时提及两个实体
- **Info Density**: 3 — 各 KU 信息量适中（比亚迪辟谣/合作、宁德科技日），但缺少两实体间的关联信息
- **Redundancy**: 2 — 宁德时代部分仍有超级科技日重复，比亚迪部分多样性较好
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股
3. ku_xxx: 小鹏、比亚迪、广汽埃安、极氪、蔚来、问界等车企通过官方账号对OTA可远程锁电传闻进行辟谣

---

## Q20260511-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | ad-hoc (relationship query) |
| **Query** | `knowledge-cli search --entities "宁德时代" --intent RELATIONSHIP_QUERY --target-entity "比亚迪" --hops 2` |
| **Intent** | RELATIONSHIP_QUERY |
| **Result Count** | 158 |
| **Relevance** | 2 |
| **Info Density** | 2 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 1.5 |

### Scoring Rationale
- **Relevance**: 2 — 关系查询期望得到两个实体间的结构化关系，但 graph_data 完全为空（0 nodes, 0 edges），退化为普通搜索
- **Info Density**: 2 — KU 内容与 ENTITY_OVERVIEW 完全相同，无任何关系信息
- **Redundancy**: 1 — 同 ENTITY_OVERVIEW 的重复问题
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股
3. ku_edb195bf4935ce09: 宁德时代举办超级科技日活动

---

## Q20260511-008

| Field | Value |
|-------|-------|
| **Date** | 2026-05-11 |
| **Session** | ut-analyst-20260511-120618 |
| **Scenario** | S008 |
| **Query** | `knowledge-cli search --entities "宁德时代" --intent EVENT_IMPACT_ANALYSIS` |
| **Intent** | EVENT_IMPACT_ANALYSIS |
| **Result Count** | 158 |
| **Relevance** | 3 |
| **Info Density** | 3 |
| **Redundancy** | 1 |
| **Temporal** | 1 |
| **Overall** | 2.0 |

### Scoring Rationale
- **Relevance**: 3 — 图谱增强了关联实体（192 nodes, 246 edges），但所有边均为 INVOLVED_IN，无因果关系或影响传导
- **Info Density**: 3 — 图谱连接了更多实体（中恒电气、陈景河等），但信息深度有限
- **Redundancy**: 1 — KU 层面同 ENTITY_OVERVIEW 的重复问题
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. em_202605113732558627_1: 宁德时代成立银川时代电服科技有限公司和兰州时代电服科技有限公司
2. ku_b2e6443029c3765d: 中际旭创取代宁德时代成为主动权益基金第一大重仓股
3. ku_edb195bf4935ce09: 宁德时代举办超级科技日活动

## Q20260516-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Scenario** | S012 (Defect #1 - non-existent entity) |
| **Query** | `knowledge-cli search --entities "不存在公司XYZ123"` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 118 |
| **Relevance** | 1 |
| **Info Density** | 1 |
| **Redundancy** | 2 |
| **Temporal** | 2 |
| **Overall** | 1.5 |

### Scoring Rationale
- **Relevance**: 1 — 20条KU中0条与"不存在公司XYZ123"相关。BM25回退匹配了完全不相关的结果（璟鸿科技、*ST黑猫、新海宜等）
- **Info Density**: 1 — 返回的信息全部关于错误实体，对查询毫无价值
- **Redundancy**: 2 — 结果中涉及多个不同实体，无明显重复，但都是噪声
- **Temporal**: 2 — 部分KU有event_time，但因全部无关而无意义

### Top 3 Results Summary
1. ku_ae64c071e007526d: 公司关于股东实际控制人... (完全无关)
2. ku_41d291baecea2ae7: *ST黑猫股票... (完全无关)
3. ku_49e13a929ec0d362: 苏州新海宜... (完全无关)

---

## Q20260524-001

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S001 |
| **Query** | `knowledge-cli search --entities "小米集团"` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 60 |
| **Relevance** | 3 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 1 |
| **Overall** | 2.8 |

### Scoring Rationale
- **Relevance**: 3 — 14/20 KU 直接提及小米（70%），6 条来自 dense retrieval 的语义关联但非直接相关内容（小鹏、茅台、亿咖通、美的等），dense noise 占 30%
- **Info Density**: 3 — KU 包含股价、产品、投资等多维度信息，但 event_time 全部为 None（0/20），信息时间维度完全缺失
- **Redundancy**: 4 — 20/20 unique summaries，无重复事件。超级科技日问题已解决（不再占满 top-K）。对比上轮（141 clusters），cluster 去膨胀效果显著
- **Temporal**: 1 — event_time 0/20 (100% None)，时间维度完全不可用。比上轮 25% 缺失率更严重

### Top 3 Results Summary
1. ku_202604103700887658_003: 权重科技股走势分化...腾讯、小米飘绿 (score: 13.66, src: dense, ent_b=10.0)
2. ku_em_202604113701725970_2: 小米于2018年登陆港交所上市 (score: 4.46, src: dense)
3. ku_524d93e5117a7e48: 小米集团-W遭南向资金净卖出24.21亿港元 (score: 4.22, src: dense)

---

## Q20260524-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S005 |
| **Query** | `knowledge-cli search --entities "小米集团" --event-types "股价变动"` |
| **Intent** | ENTITY_OVERVIEW (event type filter) |
| **Result Count** | 66 |
| **Relevance** | 5 |
| **Info Density** | 4 |
| **Redundancy** | 4 |
| **Temporal** | 1 |
| **Overall** | 3.5 |

### Scoring Rationale
- **Relevance**: 5 — "股价变动"(中文) 精确映射到 "stock_price_change"，20/20 全部匹配。Defect #2 完全修复
- **Info Density**: 4 — 股价变动 KU 包含具体涨跌幅、公司名、时间等要素，信息密度高
- **Redundancy**: 4 — 不同公司的股价变动，覆盖多样化
- **Temporal**: 1 — event_time 仍然全部缺失

### Top 3 Results Summary
1. stock_price_change KU: 权重科技股走势分化，阿里巴巴涨近3%，美团涨近1%...
2. stock_price_change KU: 权重科技股午间多数走低，小米跌超3%...
3. stock_price_change KU: 小米上市以来8年内出现两次股价"腰斩"...

---

## Q20260524-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S009 |
| **Query** | `knowledge-cli search --entities "小米集团" "腾讯控股" --intent COMPARATIVE_ANALYSIS` |
| **Intent** | COMPARATIVE_ANALYSIS |
| **Result Count** | 13 |
| **Relevance** | 2 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 1 |
| **Overall** | 2.5 |

### Scoring Rationale
- **Relevance**: 2 — 小米仅 1/13 (7.7%)，腾讯 13/13 (100%)，严重失衡。用户期望对比两家公司，却几乎只看到腾讯信息。两个实体虽都被 matched 但结果严重偏向腾讯
- **Info Density**: 3 — 腾讯相关 KU 信息量充足（AI算力涨价、QClaw、云服务等），但缺少小米维度的对比
- **Redundancy**: 4 — 无重复事件，但信息全部来自单一实体
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 权重科技股走势分化...腾讯、小米飘绿 [BOTH] — 唯一同时提及两者
2. KU2: 腾讯云将于2026年5月9日起对AI算力...涨价 [腾讯]
3. KU3: 第四届数据中心液冷技术大会...腾讯数据中心 [腾讯]

---

## Q20260524-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S009 |
| **Query** | `knowledge-cli search --entities "宁德时代" "比亚迪" --intent COMPARATIVE_ANALYSIS` |
| **Intent** | COMPARATIVE_ANALYSIS |
| **Result Count** | 36 |
| **Relevance** | 3 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.5 |

### Scoring Rationale
- **Relevance**: 3 — 宁德时代 17/20 (85%)、比亚迪 2/20 (10%)、Both 0/20 (0%)。比上轮 15:5 更偏向宁德时代，coverage_bonus 策略效果退化
- **Info Density**: 3 — 宁德时代 KU 覆盖股价、投资、合作，但无两实体间的关联信息
- **Redundancy**: 3 — 宁德时代部分 KU2/4/6/7 描述类似事件（股价涨超3.6%创新高），略有重复
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 宁德时代在香港下跌4%，受配售50亿美元股票消息影响 [宁德]
2. KU2: 创业板指涨幅扩大至1%...宁德时代持续走高 [宁德]
3. KU3: 电池ETF万家(159156)上涨2.08%，创历史新高 [NONE]

---

## Q20260524-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S012 |
| **Query** | `knowledge-cli search --entities "恒大集团" --intent ENTITY_OVERVIEW` |
| **Intent** | ENTITY_OVERVIEW |
| **Result Count** | 112 |
| **Relevance** | 1 |
| **Info Density** | 2 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 1.8 |

### Scoring Rationale
- **Relevance**: 1 — 0/20 KU 提及恒大。retrieval_mode=dense，但 dense 向量匹配到恒生指数、乐享集团等完全不相关内容。实体未匹配时 dense fallback 严重失准
- **Info Density**: 2 — 返回的 KU 有完整信息，但全部是关于错误实体的
- **Redundancy**: 3 — 涉及多个不同实体，无明显重复
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 乐享集团涨超40% (完全无关)
2. KU2: 中化岩土控股股东...股权质押风险 (完全无关)
3. KU3: 碇点金融科技由渣打银行...设立 (完全无关)

---

## Q20260524-006

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S012 |
| **Query** | `knowledge-cli search --entities "小米集团" --intent RISK_ASSESSMENT` |
| **Intent** | RISK_ASSESSMENT |
| **Result Count** | 60 |
| **Relevance** | 2 |
| **Info Density** | 3 |
| **Redundancy** | 4 |
| **Temporal** | 1 |
| **Overall** | 2.5 |

### Scoring Rationale
- **Relevance**: 2 — RISK_ASSESSMENT 现在返回不同的结果（restructuring, executive_change 类型），说明意图感知已部分实现。但 Top 5 全部关于其他公司（亿咖通/淘宝/百花医药/三星），与小米集团无关
- **Info Density**: 3 — KU 包含重组、高管变动等风险相关要素，但非查询实体
- **Redundancy**: 4 — KU3 和 KU4 是同一事件（百花医药），但总体多样性尚可
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 亿咖通科技宣布依据吉利控股集团《台州宣言》... (restructuring, 无关)
2. KU2: 雷雁群接任淘宝闪购CEO职务 (executive_change, 无关)
3. KU3: 百花医药控股股东...转让 (restructuring, 无关)

---

## Q20260524-007

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S013 |
| **Query** | `knowledge-cli search --entities "半导体" --intent TOPIC_RESEARCH` |
| **Intent** | TOPIC_RESEARCH |
| **Result Count** | 4 |
| **Relevance** | 5 |
| **Info Density** | 3 |
| **Redundancy** | 5 |
| **Temporal** | 1 |
| **Overall** | 3.5 |

### Scoring Rationale
- **Relevance**: 5 — 4/4 KU 全部关于半导体板块（兆易创新、中芯国际、华虹半导体），entity_id_lookup 精确匹配
- **Info Density**: 3 — 包含股票涨跌幅、板块信息，但仅 4 条结果信息量有限
- **Redundancy**: 5 — 4 条各不相同
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 半导体板块走强，兆易创新涨逾11%，中芯国际涨3.5%...
2. KU2: 华虹半导体低开2.2%
3. KU3: 中证港股通科技指数上涨4.51%...华虹半导体...

---

## Q20260524-008

| Field | Value |
|-------|-------|
| **Date** | 2026-05-24 |
| **Session** | ut-developer-20260524-131436 |
| **Scenario** | S013 |
| **Query** | `knowledge-cli search --entities "光刻" --intent TOPIC_RESEARCH` |
| **Intent** | TOPIC_RESEARCH |
| **Result Count** | 60 |
| **Relevance** | 2 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 2 — dense_fallback 模式，仅 1/20 KU 提及光刻（"光刻机概念盘中异动"）。Dense 向量匹配到光通信、激光等语义近似但非精确的内容
- **Info Density**: 3 — KU 信息量适中，但大部分不相关
- **Redundancy**: 3 — 无严重重复
- **Temporal**: 1 — 时间信息缺失

### Top 3 Results Summary
1. KU1: 光刻机概念盘中局部异动，海立股份涨停 (1/20 唯一相关)
2. KU2: 光库科技业绩变动...降本增效 (无关，"光"字匹配)
3. KU3: 2025年我国光通信相关企业注册量同比增加12.2% (无关)

---

## Q20260516-002

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Scenario** | S012 (Defect #2 - event type EN) |
| **Query** | `knowledge-cli search --entities "恒大集团" --event-types "debt_default"` |
| **Intent** | ENTITY_OVERVIEW (with event type filter) |
| **Result Count** | 61 |
| **Relevance** | 2 |
| **Info Density** | 2 |
| **Redundancy** | 3 |
| **Temporal** | 2 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 2 — 仅1/20条KU的unit_type="debt_default"，过滤几乎无效。多数结果为恒大集团的非债务违约事件
- **Info Density**: 2 — 信息与恒大集团相关但非请求的债务违约事件
- **Redundancy**: 3 — 结果覆盖多个不同方面（股价、投资等），无严重重复
- **Temporal**: 2 — 部分KU有event_time，但时间范围不受约束

### Top 3 Results Summary
1. ku_xxx: 恒大集团 financial_performance (非debt_default)
2. ku_xxx: 恒大集团 company_establishment (非debt_default)
3. ku_xxx: 恒大集团 debt_default (唯一匹配)

---

## Q20260516-003

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Scenario** | S012 (Defect #2 - event type CN) |
| **Query** | `knowledge-cli search --entities "恒大集团" --event-types "债务违约"` |
| **Intent** | ENTITY_OVERVIEW (with event type filter) |
| **Result Count** | 60 |
| **Relevance** | 2 |
| **Info Density** | 2 |
| **Redundancy** | 3 |
| **Temporal** | 2 |
| **Overall** | 2.3 |

### Scoring Rationale
- **Relevance**: 2 — 0/20条KU匹配"债务违约"，过滤完全无效。与英文版debt_default不同，中文版甚至0条匹配
- **Info Density**: 2 — 同英文版，信息相关但非目标事件类型
- **Redundancy**: 3 — 结果多样但非目标
- **Temporal**: 2 — 时间信息不完整

### Top 3 Results Summary
1. ku_xxx: 恒大 financial_performance (非债务违约)
2. ku_xxx: 恒大 other (非债务违约)
3. ku_xxx: 恒大 stock_price_change (非债务违约)

---

## Q20260516-004

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Scenario** | ad-hoc (time_range Apr 2026) |
| **Query** | `knowledge-cli search --entities "小米集团" --time-range "2026-04-01:2026-04-30"` |
| **Intent** | ENTITY_OVERVIEW (with time filter) |
| **Result Count** | 60 |
| **Relevance** | 4 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.8 |

### Scoring Rationale
- **Relevance**: 4 — KU内容与小米集团高度相关（股价、业务布局、卖空等）
- **Info Density**: 3 — 包含具体数据（跌幅3%、卖空降90%），但部分KU信息简略
- **Redundancy**: 3 — 有股价变动类KU重复（涨跌新闻），但多样性尚可
- **Temporal**: 1 — 时间过滤未生效，结果与无过滤完全相同。event_time=None的比例仍然偏高

### Top 3 Results Summary
1. ku_f5868c0f8b8f257f: 小米集团股价下跌超过3% (event_time=2026-04-09)
2. ku_363e499517c66118: 小米集团涨1.44% (event_time=None)
3. ku_e6fd9ace2076c7d6: 雷军介绍小米业务布局 (event_time=2026-04-13)

---

## Q20260516-005

| Field | Value |
|-------|-------|
| **Date** | 2026-05-16 |
| **Session** | ut-developer-20260516-103000 |
| **Scenario** | ad-hoc (time_range 2025) |
| **Query** | `knowledge-cli search --entities "小米集团" --time-range "2025-01-01:2025-12-31"` |
| **Intent** | ENTITY_OVERVIEW (with time filter) |
| **Result Count** | 60 |
| **Relevance** | 1 |
| **Info Density** | 3 |
| **Redundancy** | 3 |
| **Temporal** | 1 |
| **Overall** | 2.0 |

### Scoring Rationale
- **Relevance**: 1 — 请求2025年数据，返回的全部是2026年4月数据，时间过滤完全无效
- **Info Density**: 3 — KU本身信息完整，但非请求时间段
- **Redundancy**: 3 — 与Apr2026查询结果100%相同
- **Temporal**: 1 — 100%结果不在请求的时间范围内。event_time=2026-04-09出现在2025年查询中

### Top 3 Results Summary
1. ku_f5868c0f8b8f257f: 小米集团股价下跌超过3% (event_time=2026-04-09, 不在2025范围)
2. ku_363e499517c66118: 小米集团涨1.44% (event_time=None)
3. ku_e6fd9ace2076c7d6: 雷军介绍小米业务布局 (event_time=2026-04-13, 不在2025范围)
