# 本地开发与远程部署

> 本项目采用"本地开发 + git push + 远程 deploy.sh"的工作流。

## 环境概览

| 角色 | 访问方式 |
|------|---------|
| 远程服务器 | `ssh baidu`（用户 `deployer`，项目根 `/home/deployer/knowledge/`） |
| 仓库（远程） | `/home/deployer/knowledge/repo/`，跟踪 GitHub master |
| 环境变量（远程） | `/home/deployer/knowledge/.env`（API keys、NEO4J_URI、NEO4J_PASSWORD 等） |
| 数据目录（远程） | `/home/deployer/knowledge/data/`（host volume 挂载到容器 `/app/data/`） |
| MCP 端点 | `https://182-61-1-77.nip.io/mcp`（Caddy 反代，Streamable HTTP） |

## 部署流程

```bash
# 1. 本地提交并推送
git push origin master

# 2. SSH 登录服务器执行部署脚本
ssh baidu "cd /home/deployer/knowledge/repo && ./deploy.sh"
```

`deploy.sh` 自动完成：pull 代码 → docker compose build → up -d → 健康检查 → 清理旧镜像。

## 远程服务架构

Docker Compose 管理 3 个容器 + 1 个 systemd 服务：

| 组件 | 容器/服务 | 说明 |
|------|----------|------|
| Caddy | `knowledge-caddy` | 反向代理，自动 HTTPS，对外 80/443 |
| MCP Server | `knowledge-mcp` | Streamable HTTP，内部 8000，依赖 Neo4j |
| Neo4j | `knowledge-neo4j` | 图数据库，仅 Docker 内网，不对外暴露端口 |
| Ingestion | `knowledge-ingestion.service` | systemd 管理的持续离线处理（爬取 + 知识化 + 图同步） |

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
curl -s -m 15 https://182-61-1-77.nip.io/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# 工具列表
curl -s -m 15 https://182-61-1-77.nip.io/mcp \
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
