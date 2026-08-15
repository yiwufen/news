# SSH 隧道访问指南

MCP 与 Admin 已有 Cloudflare Tunnel 公网入口；其余服务通过 SSH 隧道访问，不直接对外暴露端口。

## 前置条件

```bash
# SSH 别名配置 (~/.ssh/config)
Host baidu
    HostName 182.61.1.77
    User deployer
    Port 22
```

## 服务隧道

| 服务 | 隧道命令 | 本地地址 |
|------|---------|---------|
| MCP Server | `ssh -L 8000:172.18.0.3:8000 baidu` | `http://localhost:8000/mcp` |
| Neo4j Browser | `ssh -L 17474:172.18.0.2:7474 baidu` | `http://localhost:17474` |
| Neo4j Bolt | `ssh -L 17687:172.18.0.2:7687 baidu` | `bolt://localhost:17687` |
| Admin | 无需隧道，公网访问 | `https://kg.yiyiyiwufeng.cn/admin`（Cloudflare Tunnel） |

> 容器 IP 在容器重建后会变化。查当前 IP：
> ```bash
> ssh baidu "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' knowledge-mcp"
> ssh baidu "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' knowledge-neo4j"
> ```

## 一键隧道（所有服务）

```bash
ssh -L 8000:172.18.0.3:8000 \
    -L 17474:172.18.0.2:7474 \
    -L 17687:172.18.0.2:7687 \
    baidu
```

## 数据真源（必读）

**生产真源整套在远程，本地 `data/` 只是开发用的过期副本。** 本项目没有 MySQL/Postgres，关系存储是单个 SQLite 文件，与 Neo4j 同属远程生产环境：

| 存储 | 位置 | 说明 |
|------|------|------|
| **关系库（SQLite）** | 远程 `knowledge-mcp`/`offline-new` 容器内 `/app/data/news.db` | 随 ingest 持续更新（最新写入见 `entities.updated_at`） |
| **图库（Neo4j）** | 远程 `knowledge-neo4j` 容器 | 由同一套 pipeline 写入，与 SQLite 同源同步 |

**本地 `data/news.db` 是某次开发遗留的旧快照，不可作为生产事实依据。** 它与远程 SQLite 的 `entity_id` 等主键**完全不重叠**（UUID 在每次新建实体时随机生成），用它对比远程 Neo4j 必然得到"对不上"的假象。

### 何时必须用远程数据

任何涉及"当前生产状态"的判断都必须基于远程，典型场景：

- 对比 SQLite 与 Neo4j 的主键（`entity_id` / `cluster_id`）一致性
- 验证图谱召回是否真的为 0（用本地 SQLite 的 id 喂给远程 Neo4j 必然空召回）
- 核对 ingest 数据量、分类分布、边属性覆盖率等生产指标
- 复现用户测试（findings）报告的问题

### 同步本地数据为最新生产

需要本地复现生产行为时，先把远程 SQLite 拉下来覆盖本地：

```bash
# 1. 备份本地旧快照（以防误删）
cp data/news.db data/news.db.local-snapshot-$(date +%Y%m%d)

# 2. 从容器导出生产 SQLite
ssh baidu "docker cp knowledge-mcp:/app/data/news.db /tmp/news_prod.db"

# 3. 拉取并覆盖本地（注意：先 rm 避免 scp 增量覆盖异常）
rm -f data/news.db && scp baidu:/tmp/news_prod.db data/news.db

# 4. 清理远程临时文件
ssh baidu "rm -f /tmp/news_prod.db"
```

> 容器 IP 在容器重建后会变化，操作前用 `ssh baidu "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' knowledge-neo4j"` 确认。
> 隧道端口也要随之更新：`ssh -fN -L 17687:<当前neo4j容器IP>:7687 baidu`。

### 自检清单（对照远程前问自己）

在用本地 `data/` 下任何结论前，先确认：

- [ ] 这次判断是否依赖"当前生产数据"？若是 → 必须用远程，或先同步本地
- [ ] 本地 `data/news.db` 的 `MAX(updated_at)` 是否接近今天？若不是 → 它就是旧的，结论不可外推到生产
- [ ] 拿到"对不上/全 0"的结果时，先怀疑"输入数据源错了"，再怀疑"系统坏了"

## Neo4j 连接配置

打开 `http://localhost:17474`，使用：

- **连接 URL**：`bolt://localhost:17687`
- **用户名**：`neo4j`
- **密码**：见 `.env` 中 `NEO4J_PASSWORD`

## ZCode MCP 配置

```json
{
  "mcpServers": {
    "knowledge": {
      "type": "url",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

> 使用前必须先开启 MCP 隧道。
