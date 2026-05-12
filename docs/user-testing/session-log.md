# Session Log

> Append-only 会话审计记录。

---

<!-- 在此行下方追加新会话记录 -->

## Session: ut-analyst-20260509-101500

| Field | Value |
|-------|-------|
| **Started** | 2026-05-09 10:15:00 |
| **Ended** | 2026-05-09 10:45:00 |
| **Persona** | analyst |
| **Scenarios Claimed** | S001, S002, S003, S005 |
| **Scenarios Completed** | S001, S002, S003, S005 |
| **Findings Filed** | F20260509-001 ~ F20260509-009 (9 findings) |
| **Status** | COMPLETED |

### Summary
以金融分析师视角执行了 4 个 P0 场景（S001 基础实体搜索、S002 实体时间线、S003 关系查询、S005 事件类型过滤）。发现 9 个问题：1 个 CRITICAL（关系查询静默降级）、2 个 HIGH（时间线覆盖不足、event_type 词表断层确认、恒大数据缺失）、3 个 MEDIUM（cluster 过度扩展、Neo4j 错误信息暴露、stdout JSON 污染）、2 个 LOW（entity_type 误分类、event_time 为 None）。验证了已知缺陷 #1、#2、#3、#9、#10、#12、#13、#15。Neo4j 图数据库未运行导致图谱相关功能全部不可用。

## Session: ut-developer-20260509-154500

| Field | Value |
|-------|-------|
| **Started** | 2026-05-09 15:45:00 |
| **Ended** | 2026-05-09 16:15:00 |
| **Persona** | developer |
| **Scenarios Claimed** | ad-hoc 新能源领域探索 |
| **Scenarios Completed** | 6 组搜索（比亚迪、宁德时代、新能源汽车、光伏、时间线、对比分析） |
| **Findings Filed** | F20260509-010 ~ F20260509-013 (4 findings) |
| **Status** | COMPLETED |

### Summary
以开发者视角对新能源领域（比亚迪、宁德时代、新能源汽车、光伏）进行 6 组探索性搜索。关键发现：(1) COMPARATIVE_ANALYSIS 完全偏向宁德时代，20 条 KU 中 0 条提及比亚迪（CRITICAL）；(2) unit_type 中英文混用严重，73 个唯一值中中英文各半（HIGH）；(3) event_time 缺失率 54%（MEDIUM）；(4) cluster 过度扩展在宁德时代更严重。新能源领域数据覆盖集中在 2026 年 4 月，历史数据严重不足。跨搜索的逻辑线分析显示 cluster 间有一定关联，但因数据稀疏无法形成完整事件链。

## Session: ut-analyst-20260509-170000

| Field | Value |
|-------|-------|
| **Started** | 2026-05-09 17:00:00 |
| **Ended** | 2026-05-09 17:30:00 |
| **Persona** | analyst |
| **Scenarios Claimed** | S004, S006, S013, S014 |
| **Scenarios Completed** | S004, S006, S013, S014 |
| **Findings Filed** | F20260509-014 ~ F20260509-019 (6 findings) |
| **Status** | COMPLETED |

### Summary
从 AI 应用集成视角执行 4 个场景测试。核心发现：(1) 话题搜索能否返回结果完全取决于话题词是否在摄取时被提取为实体（CRITICAL），"量化交易"和"供应链金融"返回 0 结果；(2) 英文实体别名 BYD 完全失败（HIGH），中文简称（小米/腾讯）可正确解析；(3) 图谱增强能发现 BM25 漏掉的关联事件（正面），但只有 INVOLVED_IN 单一边类型，无法支持影响链分析。S004 确认不存在实体返回空结果但 errors 为空，AI 应用无法区分"未找到"和"系统错误"。发现实体类型分类问题持续存在（半导体=Person）。

## Session: ut-analyst-20260509-173000

| Field | Value |
|-------|-------|
| **Started** | 2026-05-09 17:30:00 |
| **Ended** | 2026-05-09 18:00:00 |
| **Persona** | analyst |
| **Scenarios Claimed** | ad-hoc (Iran exploration) |
| **Scenarios Completed** | 11 组搜索（伊朗 OVERVIEW/TIMELINE/IMPACT/RISK/TOPIC、伊朗核协议、伊朗制裁、伊朗石油、中东战争、中东局势、霍尔木兹海峡、以色列、伊朗+以色列 COMPARATIVE/OVERVIEW、伊朗+军事部署 event_type filter、BYD 复测） |
| **Findings Filed** | F20260509-020 ~ F20260509-025 (6 findings) |
| **Status** | COMPLETED |

### Summary
伊朗相关 11 组搜索深度测试。核心发现：(1) **Defect #1 实体硬门已修复**——BM25 始终执行，"伊朗"(matched_entity_ids=[])仍返回 5 条结果，"BYD"在数据库更新后从 0 变为 19 条；(2) **COMPARATIVE_ANALYSIS 严重退化**——"伊朗+以色列"比较分析返回 0 条（BM25 找到 20 候选但打分阈值全部过滤），而 ENTITY_OVERVIEW 返回 4 条高相关结果（CRITICAL）；(3) **FTS5 中文分词仍是核心瓶颈**——"伊朗核协议"和"伊朗制裁"返回 0 条，但"中东战争"(31条)和"中东局势"(11条)作为实体入库后效果良好；(4) 伊朗数据覆盖极度狭窄，仅 5 条军事片段 KU，100% event_time 缺失；(5) event_type 过滤"军事部署"返回 4 条但 2 条与伊朗无关（实体约束失效）。

## Session: ut-casual-20260510-002317

| Field | Value |
|-------|-------|
| **Started** | 2026-05-10 00:23:17 |
| **Ended** | 2026-05-10 01:15:00 |
| **Persona** | casual |
| **Scenarios Claimed** | S007, ad-hoc (芯片行业探索) |
| **Scenarios Completed** | S007 (时间范围边界), 17 组芯片行业搜索（英伟达/台积电/中芯国际/ASML/华为/海思/高通/辉达/中芯/光刻机 ENTITY_OVERVIEW、芯片/AI芯片/GPU/半导体设备/芯片制裁/光刻/芯片国产替代 TOPIC_RESEARCH、英伟达+台积电 COMPARATIVE+OVERVIEW、华为+中芯国际 COMPARATIVE、台积电 TIMELINE、NVIDIA英文、S007 4组时间范围） |
| **Findings Filed** | F20260510-001 ~ F20260510-007 (7 findings) |
| **Status** | COMPLETED |

### Summary
以 casual 商务读者（P3）视角执行芯片行业全面测试，共 17 组搜索。核心发现：(1) **"海思"搜索 0/20 命中**——BM25 短词碰撞将"海思"匹配到海思科（药企）、蓝思科技、海信等，全部 20 条结果与华为海思无关（CRITICAL）；(2) **时间范围过滤完全未生效**——4 组不同范围（窄/宽/零长度/反向）对英伟达搜索返回相同结果，time_range 在 query 和 applied_filters 中正确记录但检索完全忽略（CRITICAL）；(3) **"辉达"（NVIDIA台湾名）前2条为噪声**——同根 BM25 短 token 碰撞问题；(4) **华为+中芯国际对比分析 17:1 失衡**——数据量大的实体碾压小实体；(5) **"芯片制裁"/"光刻"/"芯片国产替代"全部 0 结果**——再次验证 Defect #3 FTS5 中文分词；(6) 实体类型分类错误在芯片行业更加突出（"台南"=Person, "一季度"=Person）。积极发现：NVIDIA 英文名有效（58条 vs 中文77条）、"中芯"简称正确解析（50条）、英伟达+台积电对比分析已改善（12:8 覆盖）。

## Session: ut-analyst-20260511-120618

| Field | Value |
|-------|-------|
| **Started** | 2026-05-11 12:06:18 |
| **Ended** | 2026-05-11 12:45:00 |
| **Persona** | analyst |
| **Scenarios Claimed** | S002, S007, S008, S010 |
| **Scenarios Completed** | S002, S007, S008, S010, ad-hoc (CATL别名/对比/关系/事件类型) |
| **Findings Filed** | F20260511-001 ~ F20260511-008 (8 findings) |
| **Status** | COMPLETED |

### Summary
以金融分析师视角执行宁德时代（CATL）专项测试，共 12 组搜索。核心发现：(1) **100% event_time 为 None**——宁德时代所有 KU 缺少时间信息，比之前测试的 54% 缺失率更严重，时间线查询完全不可用；(2) **"超级科技日"占 Top 10 的 80%**——单一事件严重挤占信息多样性，确认 Defect #11（无去重）；(3) **所有 intent 产出完全相同的结果**——OVERVIEW=RISK=GUARANTEE=TOPIC 完全一致，确认 Defect #15；(4) **RELATIONSHIP_QUERY 图谱为空**——graph_used=True 但 0 nodes/edges，图谱缺少 Entity→Entity 关系边导致多跳遍历失败；(5) **"宁德"简称解析到错误实体**——解析为"宁德"(Company)而非宁德时代。积极发现：CATL 英文别名正确解析；COMPARATIVE_ANALYSIS 改善（15:5 vs 之前 20:0）；Neo4j 运行正常（192 nodes for ENTITY_OVERVIEW）；S010 schema 验证全部通过。
