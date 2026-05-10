# Retrieval Quality Scores

> 每次 search 命令后的 4 维评分记录。
> 评分标准见 `.claude/agents/user-tester.md` 中的 Retrieval Quality Scoring 段落。
> 每条记录格式：`Q<YYYYMMDD>-<NNN>`

---

<!-- 在此行下方追加新评分记录 -->

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
