# 实体合并修复 — 后续待办

> 状态(2026-08-16 回写):数据清理与代码改动均已完成并入 master;部署诉求已由 CI 自动部署流水线承接(见待办 1 回写)
> 日期:2026-06-20(状态回写于 2026-08-16)
> 关联:`docs/design-issues/entity-resolution-analysis.md`、本次 4 个文件改动

## 已完成

### 本地代码改动(未提交,在工作区)
- `scripts/dedup_entities.py`:重构为 normalized_name 分组 + 修复 4 处结构性问题 + 事务包裹
- `src/knowledge_extractor.py`:SYSTEM_PROMPT 补 identifiers 填写规范 + schema 注入 description
- `src/entities.py`:EntityResolver 新建实体分支加写前去重护栏 warning
- `eval/entity_resolution_eval.json`:评估产出更新

回归验证(pyright 0 错误、pytest 186 passed、eval_guard PASS、F1=1.000)均通过。

### 数据清理(已完成)
- **本地 `data/news.db`**:56 组 / 79 个重复实体已合并(备份 `data/news.db.bak.20260620_210722`)
- **远程生产库**:2,235 组 / 2,235 个重复实体已合并(15,411 → 13,176),零悬挂引用,零新重复

## 待办 1:部署新代码到远程(已被 CI 自动部署取代)

> **2026-08-16 回写**:CI 自动部署流水线已于 2026-06-29 上线(commit `9a5f0a1`:master push → SSH 到生产主机执行 `deploy.sh`;`deploy.sh` 以 `git reset` + `clean` 全量同步后重建镜像,见 `6f28422`),此后 master 多次合入(07-02 / 07-14 / 07-20 / 07-24 / 08-15)均会触发部署。下文"远程停在 6-08 旧镜像 / HEAD `7855313`"为 2026-06-20 时点描述,已失效;核实远程当前版本按 `docs/SSH_TUNNEL.md` 的自检清单。

远程生产库跑的仍是 **6-08 构建的旧镜像**(git HEAD 停在 `7855313`),不含本次任何代码改动。需:

1. 本地提交 4 个文件改动并推送到 master
2. 远程 `git pull` + `docker compose build`(重建 mcp/admin 镜像)
3. 重启 mcp / admin / ingestion 容器
4. 验证护栏生效:`docker logs repo-mcp-run-* | grep "Entity guard"` 应无输出(或仅在真实回归时出现)

> 注:`sudo systemctl stop knowledge-ingestion.service` 需要密码,部署流程需人工介入或配置免密。

## 待办 2:API 额度根因加固(重要)

### 根因推断
远程 2,235 组重复集中爆发于 **2026-05-25 ~ 05-30**,之后日常增量零新增。特征:
- 100% 同天创建的成对重复
- 99.5% canonical 完全相同(纯复制,非简称变体)
- 几乎像"实体缓存为空、匹配环节完全失效"

**最可能根因**:该时段 embedding / description / alias 生成依赖的外部 API(LLM / embedding service)额度耗尽或限流,导致:
- `EntityResolver` / `entity_context_filter` 的上下文注入失败
- LLM 产出不一致的 mention 形态
- 异常未被 fail-fast 拦截,静默降级导致每个 mention 新建实体

### 加固已完成(2026-06-20)

已针对重复实体的级联根因实施 **严格 fail-fast + 熔断器** 加固:

- **`src/pipeline/circuit_breaker.py`(新增)**:`CircuitBreaker` 跟踪连续增强失败次数,达阈值(默认 5)抛 `CircuitOpenError` 中断当前 run,防止 API 故障期间持续制造脏数据。
- **`src/entities.py`**:新增 `EntityEnhancementError`;`EntityResolver` 注入熔断器,mention 循环顶部 `check()`;description / alias / embedding 三处静默降级改为抛异常(fail-fast)。成功时 `record_success()` 重置计数。
- **`src/entity_description.py` + `src/alias_generator.py`**:`generate()` 移除 `except → 返回空值` 的静默降级,API 失败时异常向上传播。
- **`src/pipeline/continuous.py`**:装配熔断器;`run()` 主循环捕获 `CircuitOpenError` 并中断 run;Stage 2 区分 `EntityEnhancementError`(记录熔断失败 + 文档 failed)、`CircuitOpenError`(向上传播中断)和其他异常。新增 `embedding_provider` / `description_generator` / `alias_generator` 注入参数(便于测试隔离 API)。

**熔断恢复路径**:熔断后 run 提前结束 → systemd `Restart=always` 重启 ingestion → 新进程 = 新熔断器实例(重置)→ 失败文档增量模式重试。

回归验证:pytest 198 passed、pyright 改动文件 0 错误、eval_guard PASS、实体解析 F1=1.000。

### 后续可选增强(未做;2026-08-16 回写:确认仍未实施,保持开放)
- 熔断器半开状态(half-open):tripped 后定时试探,成功则恢复 —— 当前用进程重启重置简化
- 按异常类型区分:429(额度耗尽,需人工)vs 瞬时网络错误(应重试不熔断)—— 当前统一处理

## 待办 3:历史悬挂清理(低优先级)

> 2026-08-16 回写:远程库的悬挂在 06-22 清理时已一并修复(见下文注);本地 `data/` 只是可选的过期开发副本(约定见 `docs/SSH_TUNNEL.md`),本待办仅在本地库重新作为工作副本时才需要处理,维持低优先级。

本地库存在的历史悬挂(非本次引入):
- `cluster_entity_map`:`ent_3b051eddcfa4` → `clu_7110e2af298b`(entity 已不存在)—— 注:远程库清理时已被一并修复
- 荣耀实体 `source_ku_ids` 含错误引用 `ku_20260415_002`(内容是"阿拉格齐",与荣耀无关)

可选:写一致性修复脚本扫描 `source_ku_ids` / `entity_ids` 双向引用,清理孤儿记录。

## 待办 4:unhealthy 容器 healthcheck 配置(已完成)

> 2026-08-16 回写:已实现按角色判定的健康检查——`docker/healthcheck.py` 对 MCP 容器检查 8000 端口可达,对 ingestion / fetch 循环容器检查 `offline.log` / `fetch.log` 的写入新鲜度(容忍约 3 个周期),`docker-compose.yml` 已接入该脚本。下文为当时的问题描述,保留作背景。

`repo-mcp-run-*` 和 `knowledge-fetch` 容器状态显示 `(unhealthy)`,原因是 healthcheck 继承了 mcp 服务的 `connect localhost:8000` 检查,但这些容器跑的是离线 CLI / 爬虫,不监听 8000 端口。

应:为不同角色的容器配置各自的健康检查(如 CLI 容器检查进程存活,爬虫容器检查最近成功时间),或移除不适用的 healthcheck。

## 待办 5:别名层"等价实体"清理(2026-06-22 诊断)

### 背景

`dedup_entities.py` 只合并 `normalized_name` 完全相同的实体(保守精确匹配)。
精确重复 6-20 已清零后,图谱里仍"看起来像同一实体但未合并"的还有 **211 组**——
它们是 `normalized_name` 不同、但别名关系指向同一对象的候选(如 `港交所` / `香港交易所`)。

### 为什么不能用启发式自动合并

诊断期间试写了一个基于名称模式的分类器(国家前缀/子品牌后缀/结构后缀),对这 211 组
做自动归类,**误判率 >20%**:

- `通用` / `通用电气`(GE) / `通用汽车`(GM):表面是前缀关系,实为两家不同公司
- `华为` / `华为乾崑`:乾崑是华为独立子品牌
- `海信` / `海信家电`:海信家电是独立上市子公司(000921)
- `日产` / `东风日产`:东风日产是中日合资公司,独立法人

名称模式无法区分"全称-简称对"和"母子/合资品牌对",**批量自动合并会制造无法回滚的
实体误并,比重复更严重**。

### 已执行清理(2026-06-22,本地库)

改用**强信号 + 人工逐对复核**:筛选 `A.canonical` 与 `B.canonical` **互为别名 +
类型一致**的对,再人工核对 description / identifiers / source KU 内容。

- 脚本:`scripts/merge_alias_entities.py`(显式 hardcoded 配对清单,append-only)
- 合并 **14 对**(`MERGE_PAIRS`),primary 选 KU 数最多的(保留最多证据),225 个 KU 引用重写
- 完整性校验:实体 6247→6233,14 对 primary KU 全部正确累加,**零悬挂引用**(2 个历史
  悬挂为待办 3 遗留,非本次引入)
- 回归:pyright 0 错误,pytest 208 passed

### 复核后排除的对(不应合并)

| 对 | 排除原因 |
|----|---------|
| `西矿集团` / `西部矿业` | 西矿集团是西部矿业**控股股东**(母公司),desc 已明示 |
| `吉利控股集团` / `吉利汽车` | 控股集团 vs 港股上市子公司,独立主体 |
| `中国国防部` / `国防部` | `国防部` 是**脏实体**——11 个 source KU 混合了美/沙/科/中/德/法多国国防部,需**拆分**而非合并 |

### 未覆盖问题(独立跟踪)

> 2026-08-16 回写:`scripts/merge_alias_entities.py` 已提交入 master(commit `77f4410`);下述"历史 alias 污染扫描"与"国防部脏实体拆分"截至回写日未见处理记录,仍开放,需人工确认。

- **历史 alias 污染**:部分实体的 aliases 错误包含了另一独立实体的 canonical(如
  `中通客车.aliases` 含 `中通`,会让后续抽取把"中通客车"误并到"中通快递")。
  正确修法是**删除错误别名**而非合并实体。需单独扫描清理。
- **脏实体 `国防部` 拆分**:按 KU 实际语境(美国/中国/沙特等)拆成多个独立实体,
  需逐条 KU 重新归位,工作量大,低优先级。
- `MERGE_PAIRS` 是 append-only 清单;后续若发现新的"互为别名"等价对,按同样的
  复核标准追加,不要改成启发式自动发现。

### 远程生产库(2026-06-22 同步)

对远程库(13433 实体)重复同一诊断流程后,**本地的 14 对清单基本不适用**——两个库的
实体形态已分叉:

| 维度 | 本地 | 远程 |
|------|------|------|
| 实体总数 | 6247→6233 | 13433 |
| 6-15 后新增 | 0(本地未跑 pipeline) | 2371(健康增量,无精确重复) |
| 精确重复组 | 0 | 0 |
| 互为别名等价对 | 17(合并 14) | **3**(与本地 0 重合) |

远程 14 对中 **11 对的简称实体根本不存在**(五角大楼/工信部/EIA/港交所/小米/白宫/中通/
丽珠医药 等)——6-20 那轮远程 dedup 清理得更彻底(2235 组 vs 本地 56 组),简称早已
归并到全称。

远程 3 对复核结果:
- **ITER组织 ↔ ITER**:✓ 已合并(同一组织,KU 5+2=7,零悬挂)
- **华虹公司 ↔ 华虹半导体**:⚠️ 边界(华虹 A 股 688347 vs 港股 1347,同集团两个上市主体),
  暂不合并
- **小米汽车 ↔ 小米集团**:✗ 排除(小米汽车是子公司独立产品线;别名关系来自 alias 污染)

远程本次仅执行 ITER 1 对合并,完整性校验:实体表 / KU 引用 / cluster_entity_map /
entity_aliases / entity_identifiers **全部零悬挂引用**。

> 经验:**本地库不能作为远程清理的真源**。两个库分叉后,每次清理都必须在目标库上
> 重新跑诊断(互为别名 + 类型一致 + 逐对复核 description/KU),不能套用对端清单。
> `scripts/merge_alias_entities.py` 的 MERGE_PAIRS 是本地库的清单,对远程需另起清单
> 或走一次性脚本。

## 待办 6:Neo4j 图谱孤儿节点(2026-06-22 修复)

### 根因

`KnowledgeGraphSync.sync()`(`src/knowledge_graph_sync.py`)只做 `MERGE (e:Entity
{id:$id})` upsert,**没有任何删除路径**。SQLite 侧的实体合并(`dedup_entities.py` /
`merge_alias_entities.py` 删 dup_id)不会传播到 Neo4j,旧 `entity_id` 作为孤儿节点
留在图里,且仍挂着 `INVOLVED_IN` 边指向 EventCluster——这些边会被 GraphRAG 当成有效
证据召回,**直接污染检索**。

### 诊断数据(远程生产库,修复前)

- Neo4j Entity 节点 10198,其中 **594 个孤儿**(在图但 SQLite 已删)
- 孤儿仍挂 **983 条** orphan→live EventCluster 的边
- 594 中 **592 个**(99.7%)是 SQLite 已合并的实体(同名存活实体存在,0 歧义)
- 其中 575 个目标存活节点已在 Neo4j(需合并两图节点),17 个目标未在图(改 id 即可)
- 2 个真硬删(宇树科技 / 上市公司董事会秘书监管规则)

### 编码加固(本次提交)

1. **`KnowledgeGraphSync.prune_orphans(live_entity_ids, name_to_live_id=None)`**(新):
   以 SQLite 当前 entity_ids 为真源,对每个孤儿按三类处理(纯 Cypher,不依赖 APOC):
   - 同名存活节点已在图 → 迁移孤儿边到存活节点(若已有同 cluster 边则
     `member_ku_ids`/`source_doc_ids` **并集合并**,证据不丢),`DETACH DELETE` 孤儿
   - 同名存活 id 在 SQLite 但不在图 → `SET o.id = live_id`(重命名,边全保留)
   - 无同名存活实体(真硬删) → `DETACH DELETE` 节点+边
   空 live_ids 拒绝执行(防误清空);单步错误收集不中断整体。
2. **`EntityRepository.get_all_ids()`**(新):轻量 `SELECT entity_id`,作 prune 真源。
3. **`src/pipeline/continuous.py`**:每 run 末尾 `sync()` 之后调一次
   `prune_orphans()`,默认开启(与 SHARED_RULES §7 "图谱默认开启"一致),孤儿只在合并时
   产生,per-run 频率足够且开销可控。
4. **`scripts/prune_graph_orphans.py`**(新):dry-run 默认的一次性修复脚本,既清存量
   也验证新代码路径。

### 远程修复执行(2026-06-22)

- 备份:`/app/data/dumps/subgraph_backup_pre_prune.json`(10209 节点 + 33163 边,
  主机可见 `/home/deployer/knowledge/data/dumps/`)。注:`neo4j-admin database dump`
  需停库 + 主机 sudo,改用 MCP 容器内 driver 逻辑备份(足够覆盖 prune 这种可逆操作)。
- 执行结果:**594 孤儿删除,887 边迁移,65 边合并**。
- 一致性校验(修复后):
  - 孤儿节点:**0** ✓
  - 悬挂边(entity 端点不在 SQLite):**0** ✓
  - 重复 entity→cluster 边:**0** ✓
  - 边数 33163 → 33096(净 −67,= 迁移+合并保留的证据 − 硬删孤儿的独有边,符合预期)

### 后续部署(已由 CI 部署承接)

> 2026-08-16 回写:与待办 1 同理,CI 自动部署(2026-06-29 起)每次 master push 都会全量同步并重建镜像,prune 相关代码已随其后的 master 合入生效。下文为 2026-06-22 时点描述,保留作背景。

- 本次仅把改动文件 `docker cp` 进 MCP 容器执行了一次性 prune,**镜像未重建**——容器
  重启后会丢失这些文件,自动 prune 不会生效。
- 需走标准部署:本地提交 → push master → 远程 `git pull` + `docker compose build`
  → 重启 mcp 容器,让 pipeline 自动 prune 长期生效。
- 远程 ingestion 服务仍在用 6-08 旧镜像(见待办 1),需一并更新。
