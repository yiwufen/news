# 本地开发与远程部署

> 本项目采用"本地开发 + git push + CI 构建镜像（GHCR）+ 远程 pull-only 部署"的工作流。

## 环境概览

| 角色 | 访问方式 |
|------|---------|
| 远程服务器 | `ssh baidu`（用户 `deployer`，项目根 `/home/deployer/knowledge/`） |
| 仓库（远程） | `/home/deployer/knowledge/repo/`，跟踪 GitHub master |
| 环境变量（远程） | `/home/deployer/knowledge/.env`（API keys、NEO4J_URI、NEO4J_PASSWORD 等） |
| 数据目录（远程） | `/home/deployer/knowledge/data/`（host volume 挂载到容器 `/app/data/`） |
| MCP 端点 | `https://kg.yiyiyiwufeng.cn/mcp`（Streamable HTTP） |
| 公网入口 | 当前公网流量全部经 Cloudflare Named Tunnel：`kg.yiyiyiwufeng.cn` / `fin.yiyiyiwufeng.cn` → `caddy:80`，不依赖域名备案；`caddy` 的 80/443 端口映射保留为备案域名直连预留（备案通过前无实际流量） |

## 部署流程

master push 后全自动（`.github/workflows/ci.yml` 三段式）：

```
push master → CI test（pytest + pyright）
            → CI build：构建镜像推 GHCR（PR 只构建不推送）
               ghcr.io/yiwufen/news-mcp:{sha-<commit>, master}
               ghcr.io/yiwufen/news-admin:{sha-<commit>, master}
            → CI deploy：SSH 执行 deploy.sh（pull-only，服务器不构建）
```

`deploy.sh` 自动完成：pull 代码（compose 配置）→ `docker compose pull`（拉 CI 构建的镜像）→
`up -d --no-build` → 健康检查 → 清理旧镜像。部署镜像由 `IMAGE_TAG` 精确锁定（CI 传
`sha-<commit>`，回退链：CI 传入 > 服务器 `.env` 持久值 > `master`），并把该 tag 持久化到
服务器 `.env`，保证 ingestion/fetch 等 systemd 单元里的 `docker compose run` 与在线服务用同一镜像。

手动部署 / 回滚：

```bash
# 手动部署当前 master 浮动 tag（或复用 .env 持久 tag）
ssh baidu "bash /home/deployer/knowledge/repo/deploy.sh"

# 回滚到某个历史 commit（tag 由 CI 按相同规则推送过）
ssh baidu "IMAGE_TAG=sha-<旧commit完整sha> bash /home/deployer/knowledge/repo/deploy.sh"
```

> **一次性服务器准备**：仓库为 private，GHCR 包同为 private，服务器需以 `deployer` 执行一次
> `docker login ghcr.io`（PAT 勾选 `read:packages`）。若 ghcr.io 拉取不通，需给 docker daemon
> 配代理（systemd drop-in）——`deploy.sh` 内的 shell 级代理变量对 `docker compose pull` 无效。

## 远程服务架构

Docker Compose 管理 5 个容器 + 1 个 systemd 服务：

| 组件 | 容器/服务 | 说明 |
|------|----------|------|
| Caddy | `knowledge-caddy` | 反向代理；映射 80/443（备案域名直连预留），当前流量经 Cloudflare Tunnel 回源 `caddy:80` |
| MCP Server | `knowledge-mcp` | Streamable HTTP，内部 8000，依赖 Neo4j |
| Neo4j | `knowledge-neo4j` | 图数据库，仅 Docker 内网，不对外暴露端口 |
| Admin | `knowledge-admin` | FastAPI 管理后台（`/admin`、`/api/v1`），内部 8001 |
| Cloudflared | `knowledge-cloudflared` | Cloudflare Tunnel 出口连接器，仅出站连接 |
| Ingestion | `knowledge-ingestion.service` | systemd 管理的持续离线处理（爬取 + 知识化 + 图同步） |

> `fin.yiyiyiwufeng.cn` 经 Caddy 反代到 `fin-trace:3001`；`fin-trace` 是服务器上独立部署的外部服务，不在本仓库 docker-compose 内。

### Docker 网络

所有容器在 `knowledge-net` bridge 网络中，通过服务名互通：
- MCP → Neo4j：`bolt://neo4j:7687`（**不是** `localhost`）
- Caddy → MCP：`http://mcp:8000`

### systemd 服务

- **knowledge-ingestion.service**：常驻离线处理循环，`Restart=always`
- 使用 `docker compose --env-file run --rm mcp python -m src.cli _run_offline`（增量模式）
- 不依赖 knowledge-mcp.service（deploy.sh 管理 MCP 容器）

## 远程运维常用命令

```bash
# 容器状态
ssh baidu "docker ps --format 'table {{.Names}}\t{{.Status}}'"

# 服务日志
ssh baidu "docker logs knowledge-mcp --tail 50"
ssh baidu "docker logs knowledge-neo4j --tail 50"
ssh baidu "journalctl -u knowledge-ingestion -n 50 --no-pager"

# 重启单个容器（不重读 .env）
ssh baidu "docker restart knowledge-mcp"

# 重建容器（重读 .env，修改环境变量后必须用这个）
ssh baidu "cd /home/deployer/knowledge/repo && docker compose up -d mcp"

# 检查远程 .env
ssh baidu "grep NEO4J /home/deployer/knowledge/.env"

# Neo4j 节点统计
ssh baidu 'docker exec knowledge-neo4j cypher-shell -u neo4j -p test1234 "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"'
```

## Neo4j 管理

Neo4j 不对外暴露端口，通过 SSH 隧道访问管理界面：

```bash
# 获取容器 IP
ssh baidu "docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' knowledge-neo4j"

# 建立隧道（本地端口:容器IP:远程端口）
ssh -L 17474:<container_ip>:7474 -L 17687:<container_ip>:7687 baidu

# 浏览器打开 http://localhost:17474
# 连接地址改为 bolt://localhost:17687
# 登录：neo4j / <NEO4J_PASSWORD>
```

### Neo4j 数据为空时手动同步

增量 ingestion 不会补录存量数据。若 Neo4j 为空（如 URI 配置变更后），需手动全量同步：

```bash
ssh baidu 'docker exec knowledge-mcp python -c "
from src.entities import EntityRepository
from src.event_merging import EventClusterRepository
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.paths import DEFAULT_DB_PATH

er = EntityRepository(DEFAULT_DB_PATH)
cr = EventClusterRepository(DEFAULT_DB_PATH)
sync = KnowledgeGraphSync()
result = sync.sync(er.get_all(), cr.get_all())
print(result)
"'
```

## MCP 服务测试

```bash
# 初始化握手
curl -s -m 15 https://kg.yiyiyiwufeng.cn/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 工具列表
curl -s -m 15 https://kg.yiyiyiwufeng.cn/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## 数据持久化

| 数据 | 存储位置 | 部署是否影响 |
|------|---------|-------------|
| SQLite + FAISS | `/home/deployer/knowledge/data/`（host volume） | 不影响 |
| Neo4j 图数据 | Docker named volume `neo4j-data` | 不影响 |

部署只重建镜像和替换容器，数据卷不受影响。

## EDD 数据流：本地与远程的职责分工

> EDD（Eval-Driven Development）的回归门禁在本地跑，但 fixture DB 产物必须在远程真实库上生成。这一节固化两者的分工、产物生命周期、以及远程执行的具体方法。

### 核心分工

| 职责 | 在哪 | 依赖什么 | 频率 |
|------|------|---------|------|
| **回归检测**（代码改动后检索是否退化） | 本地 | `tests/fixtures/eval_snapshot.db` + `eval/golden_dataset_v3.json`（都在 Git 里） | 每次改检索相关代码 |
| **真实召回评估**（绝对召回水平） | 远程全量库 | `/home/deployer/knowledge/data/news.db`（全量生产库） | 部署后按需 |
| **fixture 产物生成**（snapshot） | 远程 | 真实库 + golden 集 | golden 失效时才重跑 |

**关键约束**：本地 `data/news.db`（开发旧快照）**不能用于 EDD**——它与 golden 集的 KU id 严重失配（仅 2/1163 命中），因为爬虫持续灌新数据、本地库严重滞后。EDD 的所有真实数据依赖必须走远程。

### 产物生命周期

```
远程真实库
    │
    │  snapshot_eval_pair.py（远程跑一次）
    ▼
tests/fixtures/eval_snapshot.db ──┐
eval/golden_dataset_v3.json       ├─ 入 Git，hash 锁定成对
eval/baseline.json (metrics)      ┘
    │
    │  拉回本地，提交
    ▼
本地：eval_run.py → eval_guard.py（日常回归门禁）
```

三个产物**成对绑定**，由 sha256 hash 锁定（见 `eval/baseline.json`）。任何一方单独更新都会被 `eval_guard.py` 判为漂移硬失败。

### 何时重生成 fixture 产物

golden 集 KU id 会随抽取逻辑演进而失效（历史教训：v2 用 `em_` 前缀，后改语义化命名 `regulatory_action_*`，导致 1162/1163 失配）。**重生成信号**：

- `eval_run.py` 首跑 Recall 异常低（接近 0）→ 大概率 golden id 失效
- `snapshot_eval_pair.py` 打印"⚠ N 个目标 KU 在源库中不存在"，N 占比高
- 库经历重建（`data/news.db` 被清空重灌）

### 远程执行方法（重要：避坑指南）

远程宿主 **没有 `uv`、没装 pydantic**，必须在容器内跑。但容器有多个挂载/PATH 陷阱，必须按下面方式执行。

#### 陷阱与正确做法

| 陷阱 | 原因 | 正确做法 |
|------|------|---------|
| `-v $(pwd):/app` 覆盖容器 `.venv` | 镜像把依赖装在 `/app/.venv`，挂载整个 `/app` 会盖掉 | 挂到 **`/repo`**，不碰 `/app` |
| `PATH=/app/.venv/bin:$PATH` 被 SSH 展开 | 多层嵌套引号下 `$PATH` 被本地 shell 提前展开成 Windows 路径 | 用 `--entrypoint /app/.venv/bin/python` 直接指定解释器，**不碰 PATH 变量** |
| `uv: command not found` | 远程宿主无 uv | 进容器用镜像自带的 `/app/.venv/bin/python` |
| SSH 频繁断连 | 远程 SSH 稳定性差 | **后台执行**：`nohup script &` + 轮询 `.tmp/*.done` |
| scp 传空文件 | 本地文件在传输前被其他命令清空 | scp 前先 `ls -la` 确认本地文件非空，scp 后校验远程字节数 |

#### 可直接复用的执行模板

把要跑的命令写成独立 `.sh` 脚本（避免 SSH 嵌套转义），scp 到远程，后台执行。核心模式：

```bash
# 1. 本地写脚本（用绝对路径参数，不依赖工作目录，不碰 PATH 变量）
cat > /tmp/remote_job.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /home/deployer/knowledge/repo
rm -f .tmp/job.log .tmp/job.done
mkdir -p .tmp
docker compose run --rm --no-deps \
  -v "$(pwd):/repo" \
  -e PYTHONIOENCODING=utf-8 \
  --entrypoint /app/.venv/bin/python \
  mcp /repo/scripts/<script>.py \
  --db /app/data/news.db \
  --output /repo/<output> \
  > .tmp/job.log 2>&1
echo "EXIT=$?" > .tmp/job.done
EOF

# 2. scp 到远程（前后校验大小）
scp /tmp/remote_job.sh baidu:/home/deployer/knowledge/repo/remote_job.sh
ssh baidu "ls -la /home/deployer/knowledge/repo/remote_job.sh"  # 确认非 0 字节

# 3. 后台执行（立即返回，不卡 SSH）
ssh baidu "cd /home/deployer/knowledge/repo && nohup bash remote_job.sh > .tmp/wrapper.log 2>&1 & echo pid=\$!"

# 4. 轮询完成标志（不依赖 SSH 保持连接）
ssh baidu "cat /home/deployer/knowledge/repo/.tmp/job.done 2>/dev/null || echo RUNNING; tail -15 /home/deployer/knowledge/repo/.tmp/job.log"

# 5. 产物拉回本地
scp baidu:/home/deployer/knowledge/repo/<output> <local_path>

# 6. 清理远程临时脚本
ssh baidu "rm /home/deployer/knowledge/repo/remote_job.sh"
```

**关键三原则**：
1. repo 挂到 `/repo`（绝不挂 `/app`，会毁掉容器 venv）
2. 用 `--entrypoint /app/.venv/bin/python`（绝不靠 PATH 变量）
3. 后台 `nohup &` + 轮询 `.done`（绝不指望 SSH 保持连接）

### 完整 fixture 重生成流程

当 golden 集失效需要从头重建时，远程两步合一（生成 golden + snapshot fixture）：

```bash
# Step 1: rule-based 重生成 golden 集（基于当前库采样 + 跑检索算 rank）
docker compose run --rm --no-deps -v "$(pwd):/repo" \
  --entrypoint /app/.venv/bin/python \
  mcp /repo/scripts/eval_generate.py \
  --db /app/data/news.db \
  --output /repo/eval/golden_dataset_v3.json \
  --rule-based --target 80 --seed 42 --top-k 20

# Step 2: 基于 v3 snapshot fixture DB + baseline 骨架
docker compose run --rm --no-deps -v "$(pwd):/repo" \
  --entrypoint /app/.venv/bin/python \
  mcp /repo/scripts/snapshot_eval_pair.py \
  --golden /repo/eval/golden_dataset_v3.json \
  --source-db /app/data/news.db \
  --fixture /repo/tests/fixtures/eval_snapshot.db \
  --baseline /repo/eval/baseline.json

# Step 3: 拉回本地，首跑写入基线 metrics
scp baidu:/home/deployer/knowledge/repo/{eval/golden_dataset_v3.json,eval/baseline.json,tests/fixtures/eval_snapshot.db} ./
uv run python scripts/eval_run.py --init-baseline   # 填 baseline.json 的 metrics

# Step 4: 提交三个产物（成对，hash 锁定）
git add eval/golden_dataset_v3.json eval/baseline.json tests/fixtures/eval_snapshot.db
```

> golden 版本号递增（v3 → v4...），同步更新 `retrieval-code.md` 和 `SHARED_RULES.md` 里的路径引用。
