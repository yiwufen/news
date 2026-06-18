# Admin 后台开发规则

> 后台管理系统为金融知识检索底座提供可视化运维界面。
> 技术栈：React SPA + FastAPI + Bearer Token 认证 + 独立 Docker 容器。

## 架构定位

后台是**只读为主的运维视图**，不是新的业务写入路径。

- **复用现有 Repository 层**（`KnowledgeUnitRepository`、`EntityRepository`、`EventClusterRepository`、`RawDocumentRepository`），不绕过它们直接写 SQL
- **不修改 `src/` 下现有模块的接口签名**。Admin API 是消费方，检索和 ingestion 管线是被消费方
- 写入操作（重新处理、手动合并实体等）必须调用现有管线函数，不走独立写入路径
- Admin 模块的数据访问只依赖现有 SQLite（`data/news.db`）和 Neo4j，不引入新数据存储
- Repository 依赖链：`RawDocumentRepository` 依赖 `collectors.database.Database`，admin 容器必须包含 `collectors` 包

## API 设计约定

- RESTful 风格，URL 前缀 `/api/v1/`
- 所有接口返回 JSON，错误响应统一格式：`{"detail": "描述"}`
- 列表接口必须支持分页：`page`（从 1 开始）和 `page_size`（默认 20，最大 100）
- 列表响应必须包含 `total` 总数和 `items` 数组
- 搜索接口使用 query parameter，不使用 request body for GET
- 时间参数统一 ISO 8601 格式

## 认证

- 使用 Bearer Token 认证，token 从环境变量 `ADMIN_TOKEN` 读取
- 所有 `/api/v1/` 路由默认需要认证，健康检查端点除外
- 请求头：`Authorization: Bearer <token>`
- Token 未配置时（本地开发），跳过认证检查但不打印敏感数据

## CORS

- FastAPI 必须配置 CORS 中间件，允许前端开发服务器的跨域请求
- 生产环境中，CORS origin 限定为 admin 服务自身的域名
- 本地开发允许 `localhost` 上的前端 dev server 端口

## 前端约定

- 使用 React + TypeScript
- UI 组件库优先使用 Ant Design（适合中文后台场景）
- 前端通过 Vite 开发，生产构建为静态文件
- 构建产物可由 FastAPI 直接 serve（单容器部署时），或由 Caddy 独立 serve
- 前端 API 调用统一走 `/api/v1/` 前缀，开发时通过 Vite proxy 转发到后端

## Docker 部署

### 容器策略

admin 容器负责数据读写操作（Phase 1 只读，Phase 2 写入），数据卷以读写方式挂载。

在 `docker-compose.yml` 中新增 `admin` 服务：

```yaml
admin:
  build:
    context: .
    dockerfile: Dockerfile.admin
  container_name: knowledge-admin
  restart: unless-stopped
  env_file: /home/deployer/knowledge/.env
  volumes:
    - /home/deployer/knowledge/data:/app/data
  networks:
    - knowledge-net
  depends_on:
    - mcp
```

### Dockerfile.admin

使用多阶段构建：第一阶段 Node 构建前端静态文件，第二阶段 Python 运行 FastAPI 服务并内嵌前端产物。最终镜像只包含 Python 运行时 + 前端构建产物。

### 数据访问

- SQLite 已启用 WAL 模式和 `busy_timeout=5000`，admin 并发读取不会阻塞 ingestion 写入
- Neo4j 通过 `knowledge-net` 内网访问，连接字符串 `bolt://neo4j:7687`

### 管线状态

管线状态（fetch/offline 进程）通过宿主机的 PID 文件和 Docker API 获取，不在 admin 容器内直接管理。具体方案：
- 容器状态（mcp、neo4j）：通过 Docker Engine API 查询
- systemd 服务（ingestion）：通过 SSH 远程命令或专用 API 端点查询
- 本地开发：复用 `process_manager.py` 的 PID 文件机制

### Caddy 路由

Caddy 配置新增 `/admin` 路由指向 admin 容器。

## 开发约束

- `src/admin/` 下的代码不得修改 `src/` 其他模块的代码（除非是公认的接口扩展）
- Admin API 不引入对前端框架的 Python 依赖（前端是独立构建链）
- 新增 Python 依赖只加在 `[project.dependencies]` 中，使用 `uv add` 管理
- 前端依赖使用 `npm`/`pnpm`，锁文件提交到仓库
- API 响应模型使用独立的 Pydantic schema，不直接返回内部 ORM/Repository 模型

## 开发流程

1. 后端先行：先实现 API 端点，用 curl / Swagger UI 验证
2. 前端对接：API 稳定后再开发前端页面
3. 本地开发：后端 `uv run uvicorn src.admin.app:app --reload`，前端 `cd frontend && npm run dev`
4. 提交前：`uv run pyright src/admin/` 确保类型检查通过

## Phase 2 写入操作约束

Phase 2 新增的写入功能（手动合并实体、重新触发处理、EventCluster 调整等）必须遵守：

- **操作可逆**：合并/修改前自动备份快照，支持撤销
- **不绕过管线**：重跑处理走现有 `run_pipeline()` / `run_continuous()` 函数
- **审计日志**：记录谁在什么时候做了什么操作
- **数据卷读写**：Phase 2 启用后数据卷以读写方式挂载（已在上文调整）
