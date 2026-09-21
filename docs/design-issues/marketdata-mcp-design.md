# 股票行情检索 MCP 工具设计方案

**日期**: 2026-09-21
**版本**: v1.2（v1.1 并入限流事故复盘后的架构调整；v1.2 并入 review 修复：
日K双源容错、除权检测语义修正、主数据港股累积保留、suggest 解析修正）
**状态**: 设计定稿，进入实现
**范围**: A股 + 港股正股 + 常用指数的实时行情与历史日K检索

---

## 执行摘要

为 MCP 服务器新增股票价格检索能力，采用**主数据落库 + 行情实时直连**的混合架构：
股票名单（代码/名称/市场）落本地 SQLite，名称解析不依赖上游；实时行情走多源
failover 直连（东财主源 + 腾讯备源）；历史日K按需拉取落库、增量合并、除权重拉。

核心设计原则：**稳定性优先**——多源冗余、熔断冷却、显式 stale 降级（禁止静默降级，
符合 `docs/SHARED_RULES.md` 第 7 节 guardrail）。

## 一、数据源选型（2026-09-21 盘中实测）

| 接口 | 用途 | 实测结论 |
|---|---|---|
| 东财 `push2.eastmoney.com/api/qt/ulist.np/get` | 实时行情批量（A股+港股统一 secid） | ✅ ~0.35s/次，连测 3 次稳定 |
| 东财 `push2his.eastmoney.com/api/qt/stock/kline/get` | 历史日K（fqt 支持前复权） | ✅ 贵州茅台 6009 根 |
| 东财 `searchapi.eastmoney.com/api/suggest/get` | 名称/拼音→代码（在线兜底） | ✅ 可用；空结果返回 `Data: null`（解析层已兼容） |
| 东财 `push2.eastmoney.com/api/qt/clist/get` | ~~全量股票列表~~ | ❌ **已弃用**：连续翻页触发域名级封禁（见事故复盘） |
| 新浪 `Market_Center.getHQNodeData` | 全量列表（主数据专用） | ✅ A股 5564 只，num 上限 100，56 页 |
| 腾讯 `qt.gtimg.cn/q=` | 备源实时行情 | ✅ GBK 编码，A/H 前缀不同 |
| 腾讯 `ifzq.gtimg.cn/appstock/app/fqkline/get`（A股/沪深指数）、`.../hkfqkline/get`（港股/港股指数） | 备源日K（v1.2 新增） | ✅ 前复权；键 `qfqday`（指数 `day`）；单次约 800 根上限；行内**无成交额**（amount=0）；请求 n 根可能回 n+1 根，解析层截尾归一 |
| 新浪 `hq.sinajs.cn/list=` | 三备（二期） | ⚠️ 强制 Referer（无则 403）、GBK、A/H 格式不一致 |

**选型结论**：东财主源（quote/kline/suggest 覆盖需求、免 key、JSON 结构化）+
腾讯备源；主数据列表用新浪源（分域隔离）。不引入 akshare / tushare（重依赖、
聚合层接口随上游漂移 / token+积分配额），复用项目已有 httpx 与爬虫经验。

## 一·一、限流事故复盘（2026-09-21 实测）

开发中端到端验证时触发真实限流，据此调整架构：

**事故经过**：clist 连续翻页（~33 页 × 0.65s 间隔）后东财持续断连；
探测显示封禁为 **push2 域名级**（同域的实时行情 ulist 连坐失效，kline/
suggest/其他域名不受影响），窗口超过 6 分钟（未测得上限）。页级短重试
（1s/3s）在封禁窗口内无效。

**架构整改**：
1. **主数据源与行情源分域**：列表同步改走新浪 `Market_Center` 接口
   （即使新浪限流也不影响行情链路）；东财 clist 代码整体移除。
2. **港股不落全量**：无已验证的港股全量列表源（东财 clist 已弃用、
   新浪港股节点不可用）。港股解析走 suggest 在线兜底 + 回写累积，
   热门标的自然沉淀进本地主数据。
3. **列表翻页带断点续传**：页级失败按 1s/5s/15s/30s 退避从失败页继续
   （而非整体重拉），页间隔 0.4s。
4. **failover 部分覆盖补缺**：主源响应正常但缺个别 secid（如东财不
   覆盖恒生科技指数）不算源失败、不熔断，缺失项自动走备源补拉——
   实测恒生科技由腾讯补回。
5. **suggest 兜底优先精确名匹配**：多候选中恰有一条名称与查询完全
   相等时直接解析（解决"腾讯控股"被 ADR 干扰项打成 ambiguous）。

事故本身验证了两个设计前提：failover 链在主源被封时正常接管（期间
行情全部由腾讯返回）；显式 stale/no_data 契约保证缺项可见。

**风险认知**（详见对话记录 2026-09-21）：push2 属公开网页接口，无 SLA。
本项目用量（agent 低频、批量接口、TTL 缓存去重、主数据/K线落库后不打上游）
远低于风控阈值；接口漂移风险靠响应 schema 校验 fail-fast 应对。

## 一·二、源稳定性下午复测（2026-09-21 14:44–15:10，v1.2 整改依据）

review 阶段对本机（开发+部署同机、家庭 NAT 出口）做温和实测，发现比
上午事故更强的信号：

- **东财 WAF 按 TLS 指纹选择性断连 httpx**：同一秒同一 URL，curl 返回
  200 而 httpx 报 "Server disconnected"。已排除连接复用（背靠背热连接
  也断）、请求头、`transport retries=1`（只覆盖建连失败）、IPv6（本机
  无路由）等因素——差异只剩 Python/OpenSSL 的 ClientHello 指纹。
- **封锁按域名独立、分钟级滚动翻转**：push2 与 push2his 各自独立进出
  封锁窗口（复测中 push2 被封 >5min 而 push2his/searchapi 正常；早些
  时候正好相反），与上午"push2 域名级封禁、其他域名不连坐"同构。
- 约 40 次请求摊在 20 分钟的温和用量仍多次触发；"agent 低频用量远低于
  风控阈值"的前提在本机存疑（IP 可能因上午事故处于降权状态）。
- 腾讯（qt/ifzq）与新浪（vip 列表）全程 100% 可用，无需 Referer 也通。

**v1.2 整改**（详见各模块实现）：

1. **日K补齐与行情同级的容错**：东财主源 + 腾讯 ifzq 备源 failover、
   熔断、同源重试退避；全源失败时有本地缓存返回 `degraded: true`，
   无缓存返回结构化 `error`（原先 ProviderError 直接穿透成 MCP 异常）。
2. **除权检测语义修正**：只比对"早于本地最新一根"的重叠日期。盘中
   当日 close 变化是常态（修复前每次盘中调用都误判除权 → 增量+全量
   双请求 + 整表重建）；当日 bar 的更新交给增量 upsert（INSERT OR
   REPLACE）。
3. **除权重拉截断保护**：全量序列短于本地存量（东财不可用、腾讯仅
   ~800 根）时不替换、不把新旧复权基准混排，返回 `warning`。
4. **suggest 解析修正**：空候选按 not_found（原误标 ambiguous）；
   新增代码精确与 secid 精确匹配；secid 形式输入（`116.00700`，东财
   suggest 实测不识别）取代码部分查询后按 secid 过滤。
5. **主数据港股累积保留**：A股域全量替换只清 market 0/1，suggest 回写
   的港股行不再被 24h 同步清空（修复前与决策点 6 矛盾）。
6. 杂项：MCP 日期参数解析后归一化为 `YYYY-MM-DD`（isoparse 接受
   basic 格式/带时间串，不归一化会被字符串比较静默过滤错）+ start>end
   校验；sqlite 短连接显式关闭；同源重试加 0.3s 退避。

## 二、架构

```
agent ──► MCP 工具层（3 个工具，沿用 mcp_server.py 现有注册模式）
              │
              ├─ search_stocks ────► 本地 instruments 表（纯本地，不打上游）
              │
              ├─ get_stock_quotes ─► 内存 TTL 缓存 ─► 多源 failover 链
              │                        │              东财 ─► 腾讯
              │                        ▼
              │                   quote_snapshot 表（成功响应顺手落库）
              │
              └─ get_stock_history ► kline_daily 表 ──命中──► 直接返回
                                       │ miss/增量
                                       ▼
                                   日K failover 链：东财 push2his → 腾讯 ifzq
                                   （拉取后落库，下次走本地）
```

模块划分（新模块 `src/marketdata/`）：

| 模块 | 职责 |
|---|---|
| `models.py` | 数据模型：`Instrument`、`Quote`、`KlineBar` |
| `store.py` | SQLite 存取（WAL 模式、短连接） |
| `providers/base.py` | Provider 协议（Quote/History/List/Search）+ 响应 schema 校验 |
| `providers/eastmoney.py` | 东财 quote / kline / suggest 适配 |
| `providers/tencent.py` | 腾讯 quote 适配（GBK 解码） |
| `providers/sina.py` | 新浪全量列表适配（主数据专用，断点续传翻页） |
| `universe.py` | 主数据同步（懒加载，>24h 重拉）+ 名称解析 |
| `quotes.py` | failover 链、熔断冷却、TTL 缓存、交易时段感知、stale 降级、部分覆盖补缺 |
| `klines.py` | 日K按需拉取、增量合并、除权检测重拉 |
| `service.py` | 门面组合 + 进程级单例（熔断/缓存/连接池跨请求共享） |

## 三、存储设计

**独立数据库 `data/market.db`**（决策点 1，已确认）：行情缓存可丢弃重建、与知识库
生命周期/备份策略不同、不给知识库 schema 迁移添乱。SQLite 开 WAL。短连接模式
（每次操作开新连接），避免多线程共享连接的锁问题。

### 表结构

```sql
-- 股票主数据
CREATE TABLE instruments (
    secid       TEXT PRIMARY KEY,   -- 东财体系："1.600519" / "0.000001" / "116.00700"
    symbol      TEXT NOT NULL,      -- "600519" / "00700"
    market      INTEGER NOT NULL,   -- 1=沪 0=深 116=港
    name        TEXT NOT NULL,      -- "贵州茅台"
    pinyin      TEXT,               -- "GZMT"（suggest 提供，clist 无则置空）
    asset_type  TEXT NOT NULL,      -- "stock" / "index"
    updated_at  TEXT NOT NULL
);

-- 最近行情快照（每 secid 一行，upsert；用于 stale 降级与收盘后查询）
CREATE TABLE quote_snapshot (
    secid        TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    price        REAL, change_val REAL, change_pct REAL,
    open         REAL, high REAL, low REAL, pre_close REAL,
    volume       REAL, amount REAL,
    market_time  TEXT NOT NULL,     -- 行情时间（交易所时间）
    fetched_at   TEXT NOT NULL,     -- 抓取时间
    source       TEXT NOT NULL
);

-- 历史日K（前复权，见「除权重拉」）
CREATE TABLE kline_daily (
    secid      TEXT NOT NULL,
    trade_date TEXT NOT NULL,       -- "2026-09-21"
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL,
    PRIMARY KEY (secid, trade_date)
);
```

常用指数（上证指数 `1.000001`、深证成指 `0.399001`、创业板指 `0.399006`、
恒生指数 `100.HSI`、恒生科技 `100.HSTECH`）硬编码入 `instruments`
（asset_type=index），不依赖列表源。北交所（新浪 `bj` 前缀）一期不覆盖，
解析层过滤。

## 四、MCP 工具接口契约

沿用现有模式：参数校验在 event loop 上做、错误返回可读 `{"error": ...}`、
docstring 写明调用时机与限制（`src/mcp_server.py` 两个现有工具的写法）。

### search_stocks(query, limit=10)

纯本地查询。query 接受代码 / 中文名（包含匹配）/ 拼音前缀。返回
`{candidates: [{secid, symbol, name, market, asset_type}]}`。
同名多候选时 agent 应先调本工具消歧。

### get_stock_quotes(symbols)

- `symbols: list[str]`，每项为代码或中文名（名称先走本地解析），上限 50。
- 返回：
  ```
  quotes: [{secid, symbol, name, price, change, change_pct, open, high, low,
            pre_close, volume, amount, market_time, source, stale, as_of}]
  unresolved: [...]   # 解析失败的 symbol 显式列出，不静默跳过
  ```
- 非交易时段返回最近快照（`market_time` 即行情时间，agent 可自行判断新鲜度）。
- 上游全挂：有本地快照 → 返回且 `stale: true` + `as_of`（决策点 3，已确认）；
  无快照 → 报错「所有行情源不可用」（fail-fast，符合 guardrail）。

### get_stock_history(symbol, start_date, end_date=None, limit=500)

日K区间查询，默认前复权。本地命中直接返回；缺口区间增量拉取后合并落库。
`limit` 上限 500 根，防止撑爆调用方上下文。

## 五、稳定性机制（核心）

1. **failover 链**：东财 → 腾讯（新浪二期，决策点 4）。**quote 与日K各自
   独立成链**（v1.2）：quote 走 push2→qt.gtimg.cn，日K走
   push2his→ifzq fqkline——两链熔断状态独立，域名级封锁互不连坐。
   单请求超时 5s；超时/5xx 同源快速重试 1 次（间隔 0.3s），仍失败立即
   切下一源；端到端预算 ~15s。
2. **熔断冷却**：某源连续 3 次失败冷却 60s，冷却期直接跳过。参数
   （源顺序、超时、阈值、冷却时长、TTL）环境变量可覆盖（沿用
   `MCP_THREAD_LIMIT` 模式）。
3. **TTL 缓存（交易时段感知）**：相同 secid 集合盘中 10s 内回缓存；
   收盘后 TTL 放宽至 10min。A股/港股交易时段表内置。
4. **除权检测重拉**：前复权价格在除权后整段变化，直接缓存会腐烂。每次
   增量补拉时先比对落库最近 2 根与新拉数据，**早于本地最新一根**的日期
   收盘价对不上即删除该 secid 全部日K重拉（v1.2 语义：仅最新一根对不上
   是盘中/收盘修正，由 upsert 覆盖）。重拉结果短于本地存量时不替换、
   返回 warning（备源单次 ~800 根截断）。
5. **schema 校验 fail-fast**：东财响应校验 `rc:0` + 字段形状，腾讯校验
   字段数；形状不对按「该源失败」处理，不吐脏数据。
6. **主数据本地化**：名称解析不打上游；suggest 仅作冷门标的在线兜底。
7. **可追踪**：每次上游调用记录 source/status/latency 日志；成功响应 upsert
   `quote_snapshot`。
8. **降级契约（v1.2 扩展到日K）**：全源失败时本地有数据则显式
   `degraded: true` 返回（quotes 标 stale+as_of，history 标
   degraded/degraded_note），本地也无数据才报 error；绝不静默冒充新数据。

## 六、与现有系统的集成

- **mcp_server.py**：注册 3 个工具。行情请求走 `httpx.AsyncClient`（纯 IO，
  不占共享 to_thread limiter——该 limiter 为 4GB 宿主机内存约束而设）；仅
  SQLite 落库下放线程。这是与现有工具「阻塞检索 → to_thread」模式的**有意差异**。
- **无新依赖**：httpx、sqlite3（标准库）均已具备。腾讯 GBK 用 `bytes.decode("gbk")`。
- **进程管理**：无后台任务。主数据懒加载同步（>24h 重拉），MCP 工具首次调用触发。

## 七、错误契约

- 符号解析失败：`unresolved` 列表 + 提示先调 `search_stocks`。
- 参数越界：返回合法范围（现有工具做法，让 agent 自纠）。
- 所有源不可用且无快照：显式报错，不静默降级。

## 八、测试策略

- 用 2026-09-21 实测抓取的真实响应做 fixture（东财 quote/kline/suggest/clist、腾讯）。
- 单测覆盖：provider 解析与 schema 校验、failover 状态机（熔断进入/恢复）、
  TTL 与交易时段判断、名称解析、除权重拉、stale 降级路径。
- 不打真实上游；走 `uv run pytest` + `uv run pyright` 门禁。

## 九、已知实现期风险

1. ~~港股衍生品过滤~~（已随 clist 弃用失效；港股改为 suggest 兜底 + 回写累积）。
2. **push2 接口漂移**：无 SLA，路径/字段可能变化（smartbox 404 先例）。
   schema 校验保证失效时显式报错，修复成本限于单一 provider 解析函数。
3. **新浪列表接口同为无 SLA 网页接口**：断点续传 + 长退避兜住限流；
   即使整体失败也只影响主数据新鲜度，行情链路不受影响。

## 十、分期

- **一期（本分支）**：东财+腾讯双源、3 个 MCP 工具、主数据同步（新浪源，
  A股全量+指数）、日K落库增量、stale 降级、部分覆盖补缺。
- **二期（按需）**：新浪第三备源；baostock 日K备份源；HKEX 官方 API（港股）；
  港股全量主数据源；指数范围扩展；ETF；北交所。

## 决策记录（2026-09-21 对齐 + 事故复盘增补）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 存储位置 | 独立 `data/market.db`，不并入知识库 |
| 2 | 指数范围 | 默认 5 个常用指数硬编码 |
| 3 | 上游全挂行为 | 返回本地快照 + `stale: true` + `as_of`（无快照才报错）；v1.2 起日K同语义（degraded/error） |
| 4 | 一期备源 | quote：腾讯；v1.2 起日K：腾讯 ifzq。新浪放二期 |
| 5 | 主数据列表源（事故后） | 新浪（分域隔离），东财 clist 弃用 |
| 6 | 港股主数据（事故后） | 不落全量，suggest 兜底 + 回写累积；v1.2 起 A股域替换不清除累积行 |
| 7 | 东财 httpx 被指纹封锁（v1.2） | 不引入 curl_cffi、不调换主源：failover+熔断已实测兜住；封锁为域名级滚动式，腾讯全域稳定。若未来封锁常态化再评估 curl_cffi / 腾讯升主 |
