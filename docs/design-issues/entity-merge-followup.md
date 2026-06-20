# 实体合并修复 — 后续待办

> 状态:数据清理已完成,代码改动已就位(本地),待部署
> 日期:2026-06-20
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

## 待办 1:部署新代码到远程(未完成)

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

### 后续可选增强(未做)
- 熔断器半开状态(half-open):tripped 后定时试探,成功则恢复 —— 当前用进程重启重置简化
- 按异常类型区分:429(额度耗尽,需人工)vs 瞬时网络错误(应重试不熔断)—— 当前统一处理

## 待办 3:历史悬挂清理(低优先级)

本地库存在的历史悬挂(非本次引入):
- `cluster_entity_map`:`ent_3b051eddcfa4` → `clu_7110e2af298b`(entity 已不存在)—— 注:远程库清理时已被一并修复
- 荣耀实体 `source_ku_ids` 含错误引用 `ku_20260415_002`(内容是"阿拉格齐",与荣耀无关)

可选:写一致性修复脚本扫描 `source_ku_ids` / `entity_ids` 双向引用,清理孤儿记录。

## 待办 4:unhealthy 容器 healthcheck 配置(低优先级)

`repo-mcp-run-*` 和 `knowledge-fetch` 容器状态显示 `(unhealthy)`,原因是 healthcheck 继承了 mcp 服务的 `connect localhost:8000` 检查,但这些容器跑的是离线 CLI / 爬虫,不监听 8000 端口。

应:为不同角色的容器配置各自的健康检查(如 CLI 容器检查进程存活,爬虫容器检查最近成功时间),或移除不适用的 healthcheck。
