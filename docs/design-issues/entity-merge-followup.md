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

### 需要的加固(对应 SHARED_RULES §5/§7 的 fail-fast 要求)
当前 `EntityResolver` 和抽取链路对 API 失败的处理是 `try/except + logger.warning` 静默降级。应改为:
- LLM 抽取失败 / 返回不满足契约 → fail-fast 报错(SHARED_RULES §5 已要求,需核查 `knowledge_extractor.py` 是否全面落地)
- embedding provider 失败 → 区分"可选消歧"和"必需依赖",必需依赖失败应阻断而非静默
- 增加结构化日志:记录 API 调用失败事件,便于事后定位类似爆发

### 验证方法
- 模拟 API 限流(返回 429),确认 pipeline 行为是"报错暂停"而非"静默降级继续跑"
- 检查 `data/logs/` 是否有 05-25~30 的错误日志(可能已被轮转)

## 待办 3:历史悬挂清理(低优先级)

本地库存在的历史悬挂(非本次引入):
- `cluster_entity_map`:`ent_3b051eddcfa4` → `clu_7110e2af298b`(entity 已不存在)—— 注:远程库清理时已被一并修复
- 荣耀实体 `source_ku_ids` 含错误引用 `ku_20260415_002`(内容是"阿拉格齐",与荣耀无关)

可选:写一致性修复脚本扫描 `source_ku_ids` / `entity_ids` 双向引用,清理孤儿记录。

## 待办 4:unhealthy 容器 healthcheck 配置(低优先级)

`repo-mcp-run-*` 和 `knowledge-fetch` 容器状态显示 `(unhealthy)`,原因是 healthcheck 继承了 mcp 服务的 `connect localhost:8000` 检查,但这些容器跑的是离线 CLI / 爬虫,不监听 8000 端口。

应:为不同角色的容器配置各自的健康检查(如 CLI 容器检查进程存活,爬虫容器检查最近成功时间),或移除不适用的 healthcheck。
