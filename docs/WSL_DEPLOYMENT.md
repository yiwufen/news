# Windows + WSL2 + Docker 本地部署方案（研究稿）

> 状态：研究/设计文档，未实施。结论与小节按「决策 → 步骤 → 改动清单 → 风险」组织，
> 实施时以本文为蓝本拆 PR。截至 2026-09。
> 事实性来源：仓库内 `docker-compose.yml`、`deploy/`、`deploy.sh`、`.github/workflows/ci.yml`、
> `.zcode/rules/deployment.md`、`docs/SSH_TUNNEL.md`。

## 0. 结论（TL;DR）

把现有「Linux 服务器 + systemd + 两个 compose 项目 + Cloudflare Tunnel」的部署形态，
1:1 平移到 **Windows + WSL2（Ubuntu，启用 systemd）+ 发行版内原生 Docker Engine**：

| 事项 | 结论 |
|------|------|
| Docker 运行时 | **WSL 发行版内原生 Docker Engine（非 Docker Desktop）**，systemd 管理守护进程与应用单元 |
| 复用资产 | 应用 compose、infra compose、`deploy.sh`、三个 systemd unit + timer **全部原样复用**，只参数化主机路径 |
| 公网入口 | **保留 Cloudflare Tunnel**，但**新建独立 tunnel**（新 token），避免与旧服务器 fin-trace 耦合 |
| 定时/常驻任务 | systemd-in-WSL 复用现有 unit；若未来切 Docker Desktop，改用 compose worker 服务 |
| 镜像获取 | 维持 CI → GHCR → pull-only 部署；docker daemon 配代理（走 Windows 宿主机 7897）解决 ghcr.io 拉取 |
| 通用化核心 | 引入 `KNOWLEDGE_HOME` 单一变量参数化所有主机路径；任何新机器只改一个变量 + 一份 `.env` |
| 数据迁移 | 旧服务器停写 → tar `data/` + Neo4j volume → scp → 恢复 + 校验 → 切 tunnel |

## 1. 现状盘点：迁移对象与主机耦合点

当前生产形态（≤4G 云主机，`deployer` 用户，见 `.zcode/rules/deployment.md`）：

| 资产 | 内容 | 主机耦合点 |
|------|------|-----------|
| 应用 compose（`docker-compose.yml`） | mcp / admin / neo4j 三容器 | `env_file` 与 `volumes` **硬编码** `/home/deployer/knowledge/...` 绝对路径 |
| infra compose（`deploy/infra/`） | caddy + cloudflared | `env_file` 硬编码路径；Caddyfile 里混入 fin-trace 站点；caddy 发布 80/443（备案预留，实际无流量） |
| systemd（`deploy/*.service`） | `knowledge-mcp`（oneshot 拉栈）、`knowledge-ingestion`（常驻离线循环）、`knowledge-fetch`（常驻抓取循环）、`knowledge-ingestion.timer`（4h，`Persistent=true` 断电补跑） | WorkingDirectory / `--env-file` 硬编码路径 |
| `deploy.sh` | pull-only 部署：reset 仓库 → pull → `compose pull` → `up -d --no-build` → 健康检查 → 清镜像 | `REPO_DIR`/`ENV_FILE`/`DATA_DIR` 硬编码 |
| CI（`ci.yml`） | test → build 推 GHCR（`sha-<commit>` + `master`）→ **SSH 进服务器**执行 deploy.sh | `SERVER_HOST/USER/KEY` secrets；本地机在家宽 NAT 后，CI 无法直接 SSH |
| 数据 | SQLite + FAISS（host volume `data/`）、Neo4j（named volumes） | 数据真源当前在远程（`docs/SSH_TUNNEL.md`），迁移后反转 |
| 外部网络 | `knowledge-net`（固定名外部 bridge），**与 fin-trace 共享** | fin-trace 是同机另一个服务，经同一 caddy 对外（`fin.yiyiyiwufeng.cn`） |

关键约束：**fin-trace 与本项目只在入口层共享 caddy/tunnel，应用层无耦合**。同一 Cloudflare named tunnel 的多个 connector 之间不能按 hostname 区分流量（ingress 规则属于 tunnel，connector 只是无差别承载），所以本项目迁走时**不能把旧 tunnel token 直接搬来**，否则 `fin.*` 流量会落到没有 fin-trace 的新机器上。

> 实测核验（截至 2026-09，`ssh baidu`）：服务器上共三个 compose 项目——`repo`（应用，5 容器：
> mcp/admin/neo4j + 两个 systemd `run --rm` 拉起的 worker）、`infra`（caddy + cloudflared，
> `/home/deployer/knowledge/infra/`）、`fin-trace`（外部）。infra 的 compose 与 Caddyfile 与仓库
> `deploy/infra/` **逐字节一致**，无服务器侧漂移——`deploy/infra/` 即唯一真源，迁移直接拷贝即可。
> cloudflared 仅挂 `knowledge-net`，token 经 `/home/deployer/knowledge/.env` 注入。应用项目名为
> `repo`（目录名），故 Neo4j 卷名为 `repo_neo4j-data`——新机器目录同名布局则卷名自动对齐。

## 2. 目标拓扑

```
Windows 主机（开机自启任务 → wsl.exe -d Ubuntu）
└─ WSL2 (Ubuntu 24.04, /etc/wsl.conf: systemd=true)     ← ext4 内放全部数据，数据目录禁止挂载 /mnt/*（drvfs）
   ├─ systemd
   │   ├─ docker.service（Docker Engine，daemon 代理走宿主机 7897）
   │   ├─ knowledge-mcp.service        → 应用 compose up -d
   │   ├─ knowledge-ingestion.service  → 常驻离线知识化循环
   │   ├─ knowledge-fetch.service      → 常驻抓取循环
   │   └─ knowledge-ingestion.timer    → 4h 补跑（Persistent）
   ├─ docker network: knowledge-net（固定名外部网络）
   │   ├─ 应用 compose（$KNOWLEDGE_HOME/repo/docker-compose.yml）
   │   │   ├─ knowledge-mcp    :8000（无 host 端口，override 后发布 127.0.0.1:8000）
   │   │   ├─ knowledge-admin  :8001（同上）
   │   │   └─ knowledge-neo4j  :7687（仅内网）
   │   └─ infra compose（$KNOWLEDGE_HOME/infra/，独立项目）
   │       ├─ knowledge-caddy       （本地版 Caddyfile，去 fin 站点；host 端口可只绑 127.0.0.1）
   │       └─ knowledge-cloudflared  （新 tunnel token，仅出站，家宽 NAT 无感）
   └─ $KNOWLEDGE_HOME（默认 ~/knowledge）: repo/ .env data/ infra/
```

访问路径：

| 消费方 | 路径 | 依赖 |
|--------|------|------|
| 同机 Windows 上的 ZCode MCP | `http://localhost:8000/mcp` | WSL2 默认 localhost 转发（NAT 模式即生效） |
| 同机浏览器 Admin | `http://localhost:8001/admin` | 同上 |
| 公网（任何地方的 agent/浏览器） | `https://kg.yiyiyiwufeng.cn/mcp`、`/admin` | Cloudflare Tunnel（域名可沿用，ingress 指向新 tunnel） |
| LAN 其他设备 | 可选：Win11 22H2+ 开 mirrored networking，或 `netsh portproxy` | 仅在需要时配置 |

## 3. 关键决策

### D1 Docker 运行时：WSL 内原生 Engine（推荐），Docker Desktop 备选

| 维度 | 原生 Docker Engine in WSL | Docker Desktop（WSL2 后端） |
|------|--------------------------|----------------------------|
| 授权 | Apache-2.0，任何规模免费 | 个人/小公司（<250 人 **且** <$10M 营收）免费，否则按席收费（2026 年仍 ~$9–24/人/月） |
| 资源占用 | 轻（无额外管理 distro 与 GUI 进程） | 空闲多占 ~1–2GB |
| systemd | 可用 → **现有 4 个 unit 原样复用** | 容器在 docker-desktop distro 内，无 systemd，unit 需改造 |
| 与现有部署的 parity | 与 Linux 服务器行为一致（deploy.sh、daemon 代理 drop-in、journalctl 全部同构） | 行为有差异（代理、资源上限走 GUI 设置） |
| 易用性 | 纯 CLI，需一次性配置 | GUI、VS Code 集成、端口转发自动化 |

推荐原生 Engine：本项目已有完整的 Linux 服务器部署脚本与 systemd 单元，原生路线是「平移」而非「重写」；个人使用虽不触发 Docker Desktop 付费条款，但原生 Engine 同时消除了授权、资源、行为差异三类隐患。若之后想要 GUI，可在发行版里继续用原生 daemon，Windows 侧装 Portainer/Rancher Desktop 之类的纯管理面替代。

### D2 公网入口：新建独立 Cloudflare Tunnel（推荐）

三个选项：

1. **新建 tunnel + 沿用域名**（推荐）：Cloudflare Zero Trust 面板新建 named tunnel → 新 token 写入本地 `.env` 的 `TUNNEL_TOKEN` → 面板把 `kg.yiyiyiwufeng.cn → http://caddy:80` 的 ingress 规则从旧 tunnel 改到新 tunnel。旧服务器 tunnel 保留，只服务 `fin.*`，直到 fin-trace 自行迁移。切换是面板上一条规则的改动，秒级、可回滚。
2. 仅 LAN/localhost：不部署 cloudflared，公网能力下线。最轻，但远程 agent 无法访问，与现状倒退。
3. 家宽端口映射 + DDNS：不推荐——无公网 IPv4、备案、安全面都麻烦。

infra compose 其余不变；本地版 Caddyfile 删掉 `fin.yiyiyiwufeng.cn` 站点块，`kg.` 站点与 localhost fallback 保留。caddy 的 `ports: 80/443` 在本地机上改为 `127.0.0.1:80:80`（去 443），理由：tunnel 回源走容器网络不经过 host 端口，80 仅留给本机直接访问做调试，绑 127.0.0.1 避免与 Windows 侧 IIS/其他服务冲突（WSL NAT 模式下 host 端口实际由 WSL 持有，但保持收敛习惯）。

### D3 常驻/定时任务：systemd-in-WSL（主路线）

`/etc/wsl.conf` 开 `systemd=true` 后，`deploy/` 下 4 个 unit 安装进 WSL 即可工作：
`docker.service` 由发行版内 Docker 包提供，`Requires=docker.service` 语义成立；
`knowledge-ingestion.timer` 的 `Persistent=true` 在 WSL 重启（宿主休眠/断电后恢复）后自动补跑，正好覆盖 Windows 场景的停机。

备选（若选 Docker Desktop 路线）：把两个常驻循环改成 compose worker 服务（同一镜像 + `command:` 覆盖 + `restart: unless-stopped` + compose profile），彻底去 systemd 化。镜像 healthcheck（`docker/healthcheck.py`）本就自适应「常驻服务/离线容器」两种角色，无需改动。此路线记为后续可选优化，不阻塞本次迁移。

### D4 镜像获取：维持 GHCR pull-only，daemon 配代理

> 边界澄清：本节只涉及**镜像流**——`deploy.sh` 在本机执行时主动出站连 ghcr.io 拉镜像
> （本地 → GHCR 单向出站），不需要 GitHub 反向连入，NAT/家宽/WSL 均不构成障碍。
> **真正断掉的是触发流**：ci.yml 现有 deploy job 依赖 GitHub runner SSH 进服务器执行
> deploy.sh，家宽无公网入站后不可行，处置见 §10-7（移除或改手动触发），替代触发方式见 §9
> 「CI 自动部署」行。

- **主路线**：保持「CI 构建推 GHCR → 本地 `deploy.sh` pull」不变，部署产物与 CI 测试一致。本地机在国内家宽，ghcr.io 需代理：给 WSL 内 docker daemon 配 systemd drop-in（见 §5.2），代理指向 Windows 宿主机 `http://<宿主IP>:7897`（NAT 模式下宿主 IP = WSL 默认网关）。这是现有机制（`deployment.md` 已记载 drop-in 方案）的直接复用，只是代理地址从服务器侧换成本机 Windows。
- **降级路线**：`docker compose up -d --build` 本地构建。compose 已带 `build:` 字段，天然支持；但基础镜像（`python:3.13-slim`、`ghcr.io/astral-sh/uv:*`、`node:20-alpine`）同样要拉，代理问题躲不开，且 uv/npm 依赖还需国内镜像加速，仅作为 GHCR 不可用时的 fallback。

### D5 通用化：`KNOWLEDGE_HOME` 单变量参数化

「通用」的落点：**任何一台 Linux/WSL 机器，设一个变量 + 一份 `.env` 即可部署**。改动集中在三处：

1. `docker-compose.yml`：`env_file: ${KNOWLEDGE_HOME:-/home/deployer/knowledge}/.env`，volumes 同理。Compose v2 插值支持 env_file 路径；默认值保持现网路径，旧服务器零影响。
2. `deploy.sh`：`KNOWLEDGE_HOME="${KNOWLEDGE_HOME:-/home/deployer/knowledge}"`，三个路径变量全部由它派生。
3. systemd unit：`Environment=KNOWLEDGE_HOME=...` + 路径引用改为变量不可行（unit 的 ExecStart 不做 shell 展开），改为**生成时替换**——加一个 `deploy/install-units.sh`，把 unit 模板里的 `__KNOWLEDGE_HOME__` sed 成实际值再拷到 `/etc/systemd/system/`（顺带解决 WSL 侧 sudo 手工编辑的老问题）。

## 4. Windows 侧准备

### 4.1 前置条件与安装

- Windows 10 2004+ / Windows 11，BIOS 虚拟化开启。
- 管理员 PowerShell：`wsl --install -d Ubuntu-24.04`（含 WSL2 内核）；已有发行版则 `wsl --update` 到支持 systemd 的版本（≥0.67.6，Win11 22H2+ 预装版本即满足）。

### 4.2 `.wslconfig`（`%UserProfile%\.wslconfig`）

```ini
[wsl2]
# 资源上限：当前应用栈（neo4j 封顶 1.5G + mcp/admin + 两个 worker）2.5G 内可用，
# 8G 是含构建余量的舒适值；16G 物理内存的机器适用，8G 机器降到 memory=5GB 并保持 neo4j 现有 512m 封顶
memory=8GB
processors=4
swap=8GB

# Win11 可选增强（按需启用，缺省不开）：
# autoMemoryReclaim=gradual   # 空闲时归还内存给 Windows
# sparseVhd=true               # VHD 稀疏化，缓解「只涨不缩」（新发行版生效；旧的可 wsl --manage --set-sparse true）
# networkingMode=mirrored      # Win11 22H2+：WSL 与宿主共享网络栈，LAN 设备可直接访问（非必需，tunnel 已覆盖远程访问）
```

改后 `wsl --shutdown` 生效。

### 4.3 开机自启与电源

- **WSL 自启**：任务计划程序建系统启动任务（SYSTEM 账户，最高权限），操作 `wsl.exe -d Ubuntu-24.04`。systemd 常驻进程使发行版不会闲置停机，一条启动命令即可拉起整条链路：WSL → systemd → docker.service → knowledge-mcp.service + 两个 worker（unit 均 `Restart=always`/`unless-stopped`）。
- **电源**：服务器角色建议 `powercfg /change standby-timeout-ac 0`（交流下永不睡眠）+ 关闭快速启动对磁盘的影响评估；若必须睡眠，靠 timer `Persistent=true` 与 `Restart=always` 自动补，接受停机窗口。
- **Windows Update 自动重启**：设置活动时间段收窄重启窗口；重启后自启任务恢复整栈，无需人工。

## 5. WSL 内环境

> 前提：systemd 已启用。`wsl --install -d Ubuntu-24.04` 装出的官方镜像默认带
> `/etc/wsl.conf` 的 `[boot] systemd=true`，无需手工配置；装完 `systemctl is-system-running`
> 顺手确认一次即可（老发行版升级上来的才可能缺这条）。

### 5.1 安装 Docker Engine（发行版内，官方 apt 源）

按 Docker 官方 Ubuntu 安装文档（`get.docker.com` 或分步 apt 源；apt 源可换国内镜像）。装完：

```bash
sudo systemctl enable --now docker
docker run --rm hello-world   # 验证
docker network create knowledge-net   # 固定名外部网络，一次性
```

### 5.2 daemon 代理（拉 ghcr.io 用）

```bash
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/proxy.conf <<'EOF'
[Service]
Environment="HTTP_PROXY=http://<宿主IP>:7897"
Environment="HTTPS_PROXY=http://<宿主IP>:7897"
Environment="NO_PROXY=localhost,127.0.0.1,172.17.0.0/16,172.20.0.0/16"
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```

`<宿主IP>` = `ip route show default | awk '{print $3}'`（NAT 模式下即 Windows 宿主；若开 mirrored networking 则为 `127.0.0.1`）。注意 Windows 代理客户端需允许局域网连接（Listen on 0.0.0.0）。

### 5.3 目录布局与 .env

```bash
export KNOWLEDGE_HOME="$HOME/knowledge"     # 写入 ~/.bashrc
mkdir -p $KNOWLEDGE_HOME/{data,infra}
git clone https://github.com/yiwufen/news.git $KNOWLEDGE_HOME/repo
# .env 从旧服务器拷贝（含 API keys / NEO4J_PASSWORD / 新 TUNNEL_TOKEN）
scp baidu:/home/deployer/knowledge/.env $KNOWLEDGE_HOME/.env
```

首次部署在 Cloudflare 面板新建 tunnel，token 追加到 `.env`（`TUNNEL_TOKEN=...`），`IMAGE_TAG` 留空用 `master`。

## 6. 应用栈与 infra 启动

### 6.1 本地 override（新增 `docker-compose.override.yml`，或以 example 入库）

现 compose 不发布 mcp/admin 的 host 端口（生产经 caddy）。本地机要给同机 Windows 直连，加 override：

```yaml
# docker-compose.override.yml — 本地/WSL 专用，随 KNOWLEDGE_HOME 方案一并入库为 example
services:
  mcp:
    ports:
      - "127.0.0.1:8000:8000"   # 仅本机；WSL2 localhost 转发给 Windows 用
  admin:
    ports:
      - "127.0.0.1:8001:8001"
  neo4j:
    environment:
      # 本地内存宽裕时上调（沿用旧机的封顶机制，只调数值）：
      NEO4J_server_memory_heap_max__size: 1g
      NEO4J_server_memory_heap_initial__size: 1g
      NEO4J_server_memory_pagecache_size: 1g
```

### 6.2 infra（本地版）

`$KNOWLEDGE_HOME/infra/` 拷贝 `deploy/infra/docker-compose.yml`（env_file 路径按 D5 参数化），Caddyfile 用本地裁剪版（删 fin 站点；`ports` 改 `127.0.0.1:80:80`）。首次：

```bash
cd $KNOWLEDGE_HOME/infra && docker compose --env-file $KNOWLEDGE_HOME/.env up -d
```

### 6.3 应用栈与验证

```bash
cd $KNOWLEDGE_HOME/repo && bash deploy.sh          # pull-only，或首跑 IMAGE_TAG=master
curl -s http://localhost:8000/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
# Admin: http://localhost:8001/admin（本机）或 https://kg.yiyiyiwufeng.cn/admin（切 tunnel 后）
```

Windows 侧同地址同端口直接可用（WSL2 localhost 转发默认开启）。

### 6.4 systemd 单元

`deploy/install-units.sh`（新增，见 D5）生成并安装 4 个 unit 后 `systemctl enable --now`。此后开关机/断电恢复全自动。

## 7. 数据迁移（旧服务器 → 本地）

原则：**停写 → 冷备 → 传输 → 恢复 → 校验 → 切流**，全程可回退（旧栈停而不删）。

```bash
# 1) 旧服务器停写（容器保留，随时可回切）
ssh baidu "sudo systemctl stop knowledge-ingestion knowledge-fetch"

# 2) SQLite + FAISS + 日志（host volume 整目录打包，含 -wal/-shm）
ssh baidu "cd /home/deployer/knowledge && tar czf /tmp/knowledge-data.tgz data"

# 3) Neo4j：停容器后直接 tar named volume（社区版 dump 也行，volume tar 最直白）
ssh baidu "docker stop knowledge-neo4j && docker run --rm -v repo_neo4j-data:/data -v /tmp:/backup alpine tar czf /backup/neo4j-data.tgz -C /data . && docker start knowledge-neo4j"
# 注：卷名带 compose 项目前缀（repo_），先 docker volume ls 确认实际名

# 4) 传输（本地机可直连服务器 22 端口）
scp baidu:/tmp/knowledge-data.tgz baidu:/tmp/neo4j-data.tgz $KNOWLEDGE_HOME/

# 5) 本地恢复（本地栈先 up 一次建好卷，再 down 应用与 neo4j）
cd $KNOWLEDGE_HOME
tar xzf knowledge-data.tgz                      # 覆盖 data/
docker compose -p <本地项目名> down neo4j || docker stop knowledge-neo4j
docker run --rm -v <本地neo4j卷>:/data -v $PWD:/backup alpine sh -c "cd /data && tar xzf /backup/neo4j-data.tgz"
# 6) 起栈 + 校验（对账两边一致才切流）
bash $KNOWLEDGE_HOME/repo/deploy.sh
docker exec knowledge-mcp python -c "import sqlite3;c=sqlite3.connect('/app/data/news.db');print(c.execute('select count(*) from knowledge_units').fetchone(), c.execute('select max(updated_at) from entities').fetchone())"
docker exec knowledge-neo4j cypher-shell -u neo4j -p $NEO4J_PASSWORD "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
```

校验通过后在 Cloudflare 面板把 `kg.*` ingress 切到新 tunnel，公网恢复；旧服务器停栈观察一周再退役。`docs/SSH_TUNNEL.md` 的「数据真源在远程」叙述与隧道命令需同步改写（真源变本地 WSL，管理直接 `docker exec`，不再需要 SSH 隧道进远程内网）。

## 8. 备份（本地机成为生产后必须补的短板）

云主机有快照，家用机没有。新增 `deploy/backup.sh` + systemd timer（每日）：

1. SQLite：`sqlite3 news.db "VACUUM INTO '/backup/news-<date>.db'"`（在线一致性备份，避开直接拷 wal 的坑）。
2. Neo4j：`docker exec knowledge-neo4j neo4j-admin database dump neo4j --to-...`（社区版热 dump 需短暂停写，接受凌晨窗口）。
3. 产物写 **`/mnt/g/backups/`**（即 Windows `G:\backups`，跨出 WSL VHD——VHD 损坏时两者不共存亡），
   保留 7 天；若备份目录与发行版 VHD 在同一物理盘，防 VHD 损坏但不防整盘故障，
   需再保留一份异盘或云端副本；可选再 rclone 推对象存储异地。
4. 每季度做一次恢复演练（否则备份不可信）。

## 9. 运维要点速查

| 事项 | 处理 |
|------|------|
| 时钟漂移 | WSL2 休眠唤醒后时钟漂移 → TLS 报错（Anthropic/SiliconFlow/tunnel）。systemd 已启用，`systemctl enable --now systemd-timesyncd` 即可；症状出现时 `sudo hwclock -s` 手动对时 |
| VHD 膨胀 | `sparseVhd=true`（新盘）/ `wsl --manage Ubuntu-24.04 --set-sparse true`（存量）；deploy.sh 已含 `docker image prune` |
| 发版 | WSL 内手动 `bash deploy.sh`；回滚 `IMAGE_TAG=sha-<旧commit> bash deploy.sh` |
| CI 自动部署 | 本地机在 NAT 后，CI 无法 SSH（**触发流断了；镜像流不受影响**，见 D4 澄清）。选项：a) 手动发版（推荐，个人项目节奏足够）；b) Windows 计划任务每日自动 `deploy.sh`（自动跟进 master）；c) GitHub self-hosted runner 跑在 WSL（runner 出站轮询领任务，无需公网入站，把 ci.yml 的 deploy job 改 `runs-on: self-hosted` 即可恢复全自动）。**c 的安全前提**：本仓库 public，恶意 fork PR 可能把任务塞进你的 runner——必须同时开启仓库 Actions 设置「外部贡献者 workflow 需人工批准」，且仅 master push 的 job 调度到 self-hosted，PR 的 test/build 留在 GitHub 托管 runner。建议先 a，有需要再 c |
| 日志 | `docker logs knowledge-mcp -f`；worker 循环 `journalctl -u knowledge-ingestion -f`（与旧服务器完全一致） |
| LAN 访问 | 需要 mirrored networking（Win11 22H2+）或 `netsh interface portproxy`；默认不做 |

## 10. 实施改动清单（按 PR 拆分）

| # | 改动 | 文件 | 风险 |
|---|------|------|------|
| 1 | 路径参数化 | `docker-compose.yml`、`deploy/infra/docker-compose.yml`、`deploy.sh`（`KNOWLEDGE_HOME` 插值，默认值=现网路径） | 低：默认值不变，现网零影响 |
| 2 | unit 安装脚本 | 新增 `deploy/install-units.sh`（模板替换 `__KNOWLEDGE_HOME__`）；现有 unit 加占位符 | 低 |
| 3 | 本地 override 样例 | 新增 `docker-compose.override.yml.example`（端口发布 + neo4j 内存） | 低 |
| 4 | 本地 Caddyfile | 新增 `deploy/infra/Caddyfile.local`（去 fin、端口收敛） | 低 |
| 5 | 备份 | 新增 `deploy/backup.sh` + `deploy/knowledge-backup.timer` | 低 |
| 6 | 文档更新 | `.zcode/rules/deployment.md`（新增 WSL 章节）、`docs/SSH_TUNNEL.md`（数据真源切换）、`deploy/README.md` | 低 |
| 7 | CI deploy 目标 | `ci.yml` deploy job 移除或改为手动 workflow_dispatch（迁移期先禁用，避免 CI 部署到已停写的旧服务器） | 中：需与切换同步操作 |

## 11. 风险与开放问题

1. **fin-trace 归属**：本项目切走后，旧服务器上只剩 fin-trace + 旧 tunnel。是继续留着旧服务器养 fin-trace，还是也迁本地/另迁，需要单独决策（不在本方案内）。
2. **家用机可用性**：断电/重启后依赖「任务计划 → WSL → systemd → Restart 策略」整条自愈链路，上线后需做一次冷启动演练（直接断电重启验证）。
3. **家宽质量**：tunnel 是出站长连接，家宽 NAT/动态 IP 不影响；但上游波动会直接体现在公网端点延迟上。Cloudflare 面板有 connector 健康监控，建议加告警通知。
4. **机器规格未知**：本方案按 16G 内存舒适值写；若实际 8G，按 §4.2 括号内降配，neo4j 保持旧机 512m 封顶即可（现网 4G 都能跑）。
5. **`/mnt/*` 依赖**：所有数据、仓库、Docker VHD 必须留在 WSL ext4 内；`/mnt/*`（drvfs）上跑 SQLite/Neo4j 性能差一个数量级且 fsync 语义不可靠，**禁止把数据目录挂载为 Windows 盘符目录**。仅备份产物跨到 `/mnt/g`。
6. **迁移窗口**：停写→切流之间数据冻结，公网短暂只读；窗口预计 < 1 小时（数据量：SQLite 数百 MB 级 + Neo4j 卷，家宽上行 scp 为瓶颈）。

## 12. 上线验收清单

- [ ] Windows 重启后无人工干预，5 分钟内 `https://kg.yiyiyiwufeng.cn/health` 200
- [ ] 同机 ZCode MCP 配 `http://localhost:8000/mcp` 可用（Windows 侧）
- [ ] `docker ps` 六容器全 healthy（mcp/admin/neo4j/caddy/cloudflared + worker run 容器）
- [ ] 数据对账：KU/Entity/Cluster 行数、`MAX(updated_at)`、Neo4j 节点统计与旧服务器一致
- [ ] ingestion/fetch 循环在新库上推进（`journalctl` 无报错，`entities.updated_at` 前进）
- [ ] 备份产物出现在 `/mnt/g/backups`（Windows 侧 `G:\backups`）且可恢复
- [ ] 旧服务器停栈一周后退役，Cloudflare 旧 tunnel 仅保留 fin.*

---

### 参考来源（外部事实核验，2026-09）

- [Microsoft Learn — systemd in WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd)：WSL ≥0.67.6 支持 `/etc/wsl.conf` 启用 systemd。
- [Docker 官方定价](https://www.docker.com/pricing/) / [Docker Desktop 授权条款](https://docs.docker.com/subscription/desktop-license/)：个人与小公司（<250 人且 <$10M）免费，其余付费；Docker Engine（CLI 版）不受此约束。
- [Docker WSL 后端文档](https://docs.docker.com/desktop/features/wsl/)：Docker Desktop WSL2 集成行为。
