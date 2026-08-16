# deploy/ — 远程主机 systemd unit 文件

部署在生产主机（`deployer` 用户，`/home/deployer/knowledge/`）上的 4 个 systemd unit：

| 文件 | 用途 |
|------|------|
| `knowledge-mcp.service` | oneshot 拉起整个 MCP 栈（Caddy + MCP 服务 + Neo4j），`ExecReload` 时重建镜像 |
| `knowledge-ingestion.service` | 常驻离线知识化循环（`src.cli _run_offline`），`Restart=always` 保活 |
| `knowledge-ingestion.timer` | 每 4 小时定时触发 ingestion（随机化延迟防惊群） |
| `knowledge-fetch.service` | 常驻 EastMoney 抓取循环（`src.cli _run_fetch`），`Restart=always` 保证 one-shot 容器在主机重启后自动恢复 |

首次安装命令见各 unit 文件头部的 `# Install:` 注释（需 `sudo cp` 到 `/etc/systemd/system/` 后 `daemon-reload + enable --now`）。

## 与 CI 的关系

CI（`.github/workflows/ci.yml`）只自动化 docker compose 层面的部署（master push → SSH 执行
`deploy.sh`）。**systemd unit 变更刻意不自动化**：修改 unit 需要 root 权限，须人工在远程主机上
执行 `sudo systemctl` 操作——这正是 CI "zero sudo" 设计的边界（见 ci.yml 头部注释；`SERVER_SSH_KEY`
即供该流水线 SSH 登录 `deployer` 用户使用）。

部署工作流全貌见 `.zcode/rules/deployment.md`；远程访问方式与数据真源约定见 `docs/SSH_TUNNEL.md`。
