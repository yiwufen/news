# 图谱可检索化设计

> 本文件是知识图谱「可检索化」的最终设计，涵盖**直连边、参与边粗筛、事件闭集精排、历史数据重分类**四个部分。
>
> 依据：对主库（13,479 KU / 13,479 EventCluster / 6,233 Entity）的真实数据压测（三批共 160 条样本）。所有设计结论都有数据支撑，不靠想象。
>
> 优先级遵守 `docs/SHARED_RULES.md` 第 4 节（图谱与 GraphRAG 约定）。

## 0. 问题定位

### 0.1 原始痛点

「一个实体有成千上万个事件，多跳检索困难。」

经数据验证，真实量级被高估（最热实体只挂 108 簇，90% 实体挂 1~2 簇）。**真正的痛点不是"事件数量"，而是"想找的那一类，被淹没在同质化噪声里"**——这是区分度问题，不是数量问题。

### 0.2 三个病灶（数据证实）

| 病灶 | 数据证据 | 后果 |
|---|---|---|
| 参与边无筛选维度 | `INVOLVED_IN` 边只有 `member_ku_ids/source_doc_ids/updated_at` | 多跳只能裸跑，无法剪枝 |
| 事件类型混乱 | investment 50% 归错（压测发现）；announcement/other 垃圾桶占 20% | 精排失效，按类型筛不准 |
| 缺直连边 | 稳定关系（持股/担保）只能经事件簇间接连接 | 稳定关系查询要 zigzag，O(A簇数×B簇数) |

### 0.3 设计分四块，各治一个病灶

| 块 | 治什么 | 状态 |
|---|---|---|
| **直连边**（4类） | 稳定关系查询 | 完备性经实体对穷举验证 |
| **参与边粗筛**（scope/nature/role） | 多跳剪枝 | 机械判定，歧义率 6.9% |
| **事件闭集精排**（32类） | 事件类型筛选 | 三批共160条样本，0遗漏 |
| **历史数据重分类** | 现有库的错误归类 | ~22% KU 需重分 |

---

## 1. 直连边设计：`Entity -[:T]-> Entity`（新增）

仅收纳「稳定、可重复、结构性」的实体间关系。数据源：`relation_hints`（抽取层已产出，`knowledge_extractor.py:141`）经归一化。

### 1.1 四类直连边（闭集）

| 类型 | 语义 | subtype（开放属性） | 覆盖实体对 |
|---|---|---|---|
| `OWNERSHIP` | 谁拥有/控制谁 | 股权控制/实控人/产品归属/品牌归属 | Co→Co, Person→Co, Co→Product |
| `GOVERNANCE` | 谁管谁/谁在哪任职 | 任职/监管/隶属 | Co→Person, Org→Co, Co→Org |
| `COMMERCIAL` | 商业协作往来 | 供应/合作/投资(非控股) | Co→Co |
| `RISK` | 风险连带/对抗 | 担保/竞争 | Co→Co |

### 1.2 完备性验证（实体对穷举法）

用真实 `relation_hints`（2065 条已解析）的实体对分布，逐一验证：

| 实体对 | 占比 | 真实连接 | 4类边覆盖 |
|---|---|---|---|
| Company↔Company | 50.5% | 持股/担保/供应/合作/竞争 | ✅ 四类 |
| Company↔Organization | 19.0% | 监管/合作 | ✅ GOV+COMM |
| Company↔Person | 10.1% | 任职/实控 | ✅ OWN+GOV |
| Organization↔Organization | 7.7% | 隶属/合作 | ✅ GOV+COMM+RISK |
| Organization↔Person | 6.2% | 任职 | ✅ GOV |
| Company↔Product | 2.9% | 供应/合作(数据证实非权属) | ✅ COMM |
| Person↔Person | 2.4% | **全是一次性事件(签署/合作/会见)** | N/A(走EventCluster) |
| 其余 | ~1% | 供应/合作 | ✅ COMM |

**穷举结论：4 类边覆盖所有需要直连边的稳定关系。** Person↔Person 数据证实全是一次性事件，不进直连边（走 EventCluster）；Product 相关连接是供应/合作而非权属，归 COMMERCIAL。

> 完备性依赖当前抽取层产出。若未来抽取层开始抽"人物亲属""产品权属"，需重新评估。

### 1.3 稳定性门槛（防直连边爆炸）

一次性事件（收购/签署/发布/袭击/处罚单次）**绝不进直连边**，强制走 EventCluster。主库 3101 条 relation_hints 中，约 83% 能落直连边，15% 是一次性事件。

### 1.4 直连边属性与合并语义

| 属性 | 作用 |
|---|---|
| `subtype` | 开放子类型（见 1.1） |
| `first_seen`/`last_seen` | 首次/末次观测时间（来自 source KU） |
| `source_ku_ids` | 溯源（满足 SHARED_RULES.md「边可回溯到 KU」） |
| `confidence` | 归一化置信度 |

同一 `(A, B, type, subtype)` 重复出现 → 合并为一条边（`last_seen`取最新、`source_ku_ids`取并集、`confidence`取最大）。主库重复边占 8.2%，合并后省 9.9%。

---

## 2. 参与边粗筛：`Entity -[:INVOLVED_IN {scope,nature,role}]-> EventCluster`

保留单一类型 `INVOLVED_IN`（不拆类型），加三个边属性做粗筛。

### 2.1 设计原则

粗筛发生在多跳遍历展开邻居时。筛选维度必须满足：①判定快且确定（看客观属性，不读内容）；②减枝有效。据此筛出三个维度：

| 维度 | 取值(闭集) | 判定依据 | 数据支撑 |
|---|---|---|---|
| `scope` | corporate/environment | 事件的主体 entity_type 是否含 Company/Product | 歧义率 6.9% |
| `nature` | action/reaction | cluster_type 是否价格/行情类 | 边界清晰 |
| `role` | subject/object/mention | entity_id 是否等于 cluster.primary_entity_id | 热点簇减枝 80~90% |

### 2.2 三个维度正交

| 维度 | 分流轴 | 砍什么噪声 |
|---|---|---|
| role | 方向 | 施动者vs受动者，多跳只跟一个方向 |
| scope | 归属 | 公司的事vs外部环境的事 |
| nature | 性质 | 已发生事实vs价格/观点反应 |

组合 2×2×3=12 槽位。例：中信证券 108 簇 → `role=subject ∧ scope=corporate ∧ nature=action` → 约缩到 1/3~1/5。

### 2.3 粗筛的边界（诚实说明）

粗筛擅长砍**大类噪声**（反应/方向/归属），**不擅长区分同类里的细分**（投资vs财报）——这是精排的活。粗筛把 108 簇缩到 30，精排从 30 里筛出 8 个 investment。两层缺一不可。

---

## 3. 事件闭集精排：32 类金融事件类型

### 3.1 闭集范围：金融 + 金融影响因素

经数据验证，金融场景边界封闭，完备闭集可行。闭集范围 = 金融事件 + 金融影响因素（地缘/军事/政治影响市场）。边界外内容标 `non_financial`。

### 3.2 为什么不会膨胀

| 防膨胀机制 | 作用 |
|---|---|
| 按主体×变化穷举，非平铺 | 新类型必须落到"主体×变化"格子，否则不属金融场景 |
| 边界明确（金融 vs non_financial） | 非金融有明确出口，不挤进闭集 |
| 无垃圾桶（other/announcement 取消） | 拿不准必须落具体类型，逼精确分类 |
| non_financial 有门槛 | 不是"不知道"，是"明确非金融"，防变新垃圾桶 |

### 3.3 完整类型定义与判定优先级

#### 第一组：公司资本类（重灾区，判定优先级最严）

**判定优先级（从高到低，命中即停）：**

```
1. 股权/控制权结构变化?
   → 重组/并购/分拆                    = restructuring
   → 首次公开发行/借壳/增发/配股        = ipo
   → 股东增减持/大宗交易/股权拍卖        = shareholding_change
   → 股权质押/解除质押/冻结             = equity_pledge
2. 利润分配? → 分红/送股/转增/派息      = dividend
3. 新设主体? → 新公司/合资/子公司设立   = company_establishment
4. 投资(不改控制权)? → 股权投资/战略投资/融资/注资 = investment
```

#### 第二组：公司经营类

| 类型 | 定义 | 边界 |
|---|---|---|
| `financial_performance` | 财报/营收/利润/业绩预告/销量等量化经营成果 | 业绩说明会若核心是发布数据→此类型；回应质疑→disclosure |
| `product_launch` | 新产品/技术/服务发布，商标/研发进展 | 纯学术突破→non_financial |
| `business_strategy` | 战略/经营范围/商业模式/产能变化 | |
| `executive_change` | 高管/董事/实控人/核心人员变动 | |

#### 第三组：公司风险类

| 类型 | 定义 | 边界 |
|---|---|---|
| `debt_default` | 债务/债券违约、展期、兑付危机 | |
| `legal_proceeding` | 诉讼/仲裁/裁决(已进入法律程序) | 律师函/未起诉→disclosure |
| `risk_warning` | 退市风险/*ST/重大经营风险 | 子公司火灾若重大→此类型；纯社会新闻→non_financial |

#### 第四组：市场分析类（重灾区，判定优先级）

```
1. 有具体价格变动数字?
   → 个股股价涨跌                      = stock_price_change
   → 商品/资产/汇率价格变动              = price_change
   → 板块/概念/行业指数表现              = sector_performance
2. 机构评级/目标价/盈利预测调整?         = rating_change
3. 分析观点/研报?
   → 大盘/宏观市场行情                  = market_analysis
   → 行业/产业链研究                    = industry_analysis
```

> `rating_change` 严格指"评级/目标价/盈利预测的**调整动作**"。研报提及投资动作预测但无评级调整→industry_analysis。（此边界由压测补充。）

#### 第五~七组：监管/宏观/影响因素（边界清晰）

| 类型 | 定义 |
|---|---|
| `regulatory_action` | 监管处罚/问询/警示/立案/行政处罚 |
| `sanction` | 国际制裁/禁运/出口管制/关税制裁 |
| `policy_announcement` | 政策/法规/规划/标准/通知发布与变动 |
| `economic_data` | GDP/CPI/PMI/就业/社融等宏观指标 |
| `trade_data` | 进出口/贸易额/关税/海关数据 |
| `diplomatic_event` | 外交声明/访问/会谈/外交协议 |
| `military_action` | 军事行动/冲突/袭击/部署 |
| `political_statement` | 政治/政府表态/立场表达 |

> 外国无关选举结果→non_financial；影响本国市场的政治表态→political_statement。

#### 第八~十组：关系/披露/边界外

| 类型 | 严格定义 | 不适用情形(防垃圾桶) |
|---|---|---|
| `strategic_cooperation` | 战略合作/签署协议/达成合作(非投资性) | 含控股成分→restructuring |
| `disclosure` | 上市公司就特定事项的正式信息披露(澄清/回应/停复牌/减持计划公告) | 有具体类型(业绩/合作/风险)优先归具体类型 |
| `meeting` | 有明确金融/政策主题的会议/论坛/发布会 | 学术会议/展会无金融实质→non_financial |
| `non_financial` | 内容不属于金融或金融影响因素 | 拿不准**禁止**填此，必须落具体金融类型 |

### 3.4 完备性验证（三批压测）

| 批次 | 样本 | 来源 | 真落不进 |
|---|---|---|---|
| 第一批 | 50条 | announcement/other 垃圾桶随机 | 0 |
| 第二批 | 60条 | 垃圾桶随机(更杂,地缘/卫生多) | 0 |
| 第三批 | 24条 | 资本类+分析类重灾区(已分类) | 0(但发现现有归类50%错) |

**三批共 160 条样本，0 遗漏。** 第三批暴露现有库 investment 类型 50% 归错，详见第 5 节。

---

## 4. 检索时的分工

| 时机 | 用什么 | 在哪 |
|---|---|---|
| 多跳**展开邻居前**(粗筛) | role/scope/nature + 直连边类型(4类) | 边属性 / Cypher pattern |
| 命中后**精排**(过滤) | cluster_type(32类闭集) | 节点属性 |

### 4.1 多跳 Cypher 示例

```cypher
// 粗筛: 只展开公司层面的、已发生事实的、主体方向的邻居
MATCH path = (s:Entity)-[r:INVOLVED_IN WHERE r.scope='corporate' AND r.nature='action']*1..3]-(c:EventCluster)
WHERE s.id IN $ids AND ALL(rel IN relationships(path) WHERE rel.role='subject')

// 精排: 命中后按闭集类型过滤
WITH c WHERE c.cluster_type IN ['investment','restructuring']

// 稳定关系: 直连边直达，不 zigzag
MATCH path = (a:Entity {id:$aid})-[:OWNERSHIP*1..3]->(b:Entity)
```

---

## 5. 历史数据重分类（必须）

### 5.1 为什么必须重分类

压测发现现有库的 cluster_type 系统性错误：

| 问题 | 严重性 | 数据 |
|---|---|---|
| investment 是超级垃圾桶 | 🔴 严重 | 压测 12 条，6 条归错(50%) |
| announcement/other 垃圾桶 | 🔴 严重 | 2695 条(20%)，75%无法分流但有明确 non_financial 归宿 |
| 实体误抽 | 🔴 严重 | "海南澄迈""海南岛"被标 Company |

**新定义配旧数据 = 检索还是乱。** 必须重分类。

### 5.2 重分类依据（每条 KU 都齐全）

KU 的 payload 含 `summary` + `entities`(含 entity_type) + `evidence` + 现有 `unit_type`，足以支撑重分类判定。

### 5.3 重分类方法与工作量

| 对象 | 条数 | 方法 |
|---|---|---|
| announcement/other 垃圾桶 | 2695 | LLM 重标(需读内容判断金融类型 vs non_financial) |
| investment 误归类 | ~206(50% of 412) | 判定优先级规则可部分自动化，边界模糊的需 LLM |
| 全库 entity_type 误抽 | 待统计 | 实体清洗(非金融内容的地名/概念误标 Company) |
| **估计总工作量** | **~22% KU** | LLM 重标 + 规则辅助 |

### 5.4 重分类与闭集落地的关系

```
重分类(治旧数据) ──→ 闭集精排才有效
闭集定义(治新数据) ──→ 新抽取 prompt 用 32 类 + 判定优先级
两者必须同步，否则新旧数据不一致
```

---

## 6. 与 SHARED_RULES.md 的对齐

| SHARED_RULES.md 条款 | 本设计如何落地 |
|---|---|
| 第4节推荐边语义(269-272行) | 直连边(4类)✅；参与边加属性✅；EC→EC 暂不做 |
| 「所有边可回溯到 KU」(263行) | 直连边携带 source_ku_ids ✅ |
| 「归并策略偏保守」(326行) | 直连边稳定性门槛 + 一次性事件走 EventCluster ✅ |
| 「不修改 run_pipeline/run_continuous 接口语义」 | 粗筛/精排是内部逻辑，不暴露新参数 ✅ |

## 7. 暂不实现

| 项 | 原因 |
|---|---|
| `EventCluster→EventCluster`(因果/时间边) | 第一性原理上非多跳必需，时间靠 time_anchor 排序即可。待参与边+直连边验证后再议 |
| `EntityRef.role` 抽取层精确化 | 第一版 subject 判定用 primary_entity_id 兜底 |
| 直连边 weight 强度轴 | 91.8% 边只出现1次，无区分度(数据证伪) |

## 8. 落地改动面（实施依据）

| 文件 | 改动 |
|---|---|
| `schemas/enums.py` | 32类闭集枚举 + 判定优先级函数 + reclassify_legacy_unit_type |
| `knowledge_extractor.py` | extraction prompt 改用 32 类 + 判定优先级 + 取消 other/announcement |
| `knowledge_graph_sync.py` | 参与边写 scope/nature/role；新增直连边 sync(含合并语义) |
| `knowledge_retrieval.py` | 多跳 Cypher 加 WHERE r.scope/nature/role + 直连边类型剪枝 |
| **新增**: 重分类脚本 | 对历史 13k KU 重标 cluster_type + entity_type 清洗 |
| 回归 | 改完按 SHARED_RULES.md 第8节跑 eval_run.py + eval_guard.py |
