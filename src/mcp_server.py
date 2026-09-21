"""MCP server exposing knowledge-cli as remote tools via Streamable HTTP."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from anyio import CapacityLimiter
from anyio.to_thread import run_sync as run_sync_in_thread
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.paths import DEFAULT_DB_PATH
from src.schemas.query import IntentType, make_query

# to_thread 并发上限。anyio 默认 limiter=40，但部署宿主机仅 4GB 内存；
# 共享单例已经把每请求内存压到一份索引，这里限制并发线程数可避免极端并发
# 下线程/连接开销失控。可通过环境变量覆盖。
_DEFAULT_THREAD_LIMIT = 16


class MCPApiKeyMiddleware(BaseHTTPMiddleware):
    """API Key authentication for MCP endpoints.

    Reads MCP_API_KEY from environment. If not set, auth is skipped.
    Clients must pass ``Authorization: Bearer <key>`` header.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            api_key = os.environ.get("MCP_API_KEY", "")
            if api_key:
                auth = request.headers.get("Authorization", "")
                if auth != f"Bearer {api_key}":
                    return JSONResponse(
                        {"detail": "Unauthorized"},
                        status_code=401,
                    )
        return await call_next(request)


def create_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    db_path: str = DEFAULT_DB_PATH,
) -> FastMCP:
    """Create a configured FastMCP server with all tools registered.

    Tools are ``async def`` and offload the blocking retrieval work to a
    bounded thread pool (``anyio.to_thread.run_sync``) so the event loop is
    never blocked and multiple MCP requests can be served concurrently.
    """

    mcp = FastMCP(
        name="knowledge-cli",
        instructions=(
            "金融知识检索服务，主要覆盖中国A股和港股市场。\n"
            "\n"
            "提供两层检索工作流：\n"
            "1. search_knowledge：检索实体、事件和关系。返回知识单元、实体画像、事件聚类和图谱概览。\n"
            "2. expand_graph_detail：展开图谱聚类的完整节点/边/路径详情。需要 search_knowledge 返回的 cluster_id。\n"
            "\n"
            "行情数据工具（独立于知识库，直接查上游行情源）：\n"
            "3. search_stocks：按代码/中文名/拼音搜股票与指数，获取标准代码（消歧入口）。\n"
            "4. get_stock_quotes：批量查实时或最近收盘价（A股、港股、常用指数）。\n"
            "5. get_stock_history：查历史日K（默认前复权，含当日盘中未收盘数据）。\n"
            "\n"
            "典型工作流：先调用 search_knowledge，从返回的 graph_data.clusters_overview 中提取感兴趣的 "
            "cluster_id，再调用 expand_graph_detail 获取完整图谱结构。\n"
            "行情工作流：不确定代码时先 search_stocks 消歧，再 get_stock_quotes / get_stock_history。\n"
            "\n"
            "实体名称优先使用中文（如 '比亚迪'、'宁德时代'）；常见英文简称（如 'BYD'、'CATL'）"
            "可自动解析，冷门英文名建议先转换为中文。"
        ),
        host=host,
        port=port,
        stateless_http=True,
    )

    # Shared capacity limiter bounds concurrent blocking work across all tools.
    thread_limit = int(os.environ.get("MCP_THREAD_LIMIT", _DEFAULT_THREAD_LIMIT))
    limiter: CapacityLimiter = CapacityLimiter(thread_limit)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def search_knowledge(
        entities: list[str],
        intent: str = "ENTITY_OVERVIEW",
        time_range: str | None = None,
        event_types: list[str] | None = None,
        target_entity: str | None = None,
        hops: int = 1,
        edge_role: list[str] | None = None,
        edge_scope: list[str] | None = None,
        top_k: int = 20,
    ) -> dict[str, Any]:
        """从金融知识库中检索实体、事件和关系。支持6种查询意图，返回知识单元、实体画像、事件聚类和图谱概览。

        何时调用 / 意图选择指南：
        - 用户问某公司/人物的概况或最新动态 → ENTITY_OVERVIEW（默认）
        - 用户要求按时间线梳理某实体的事件 → ENTITY_TIMELINE
        - 用户问两个实体之间的关系（如"比亚迪和特斯拉的合作"）→ RELATIONSHIP_QUERY（必须同时设置 target_entity）
        - 用户要求比较多个实体（如"比亚迪和特斯拉的业绩对比"）→ COMPARATIVE_ANALYSIS
        - 用户问某类事件（如"最近的并购事件"）→ EVENT_ANALYSIS
        - 用户研究某个主题/产业链（如"新能源车产业链"）→ TOPIC_RESEARCH

        注：风险/担保/事件影响场景不再使用专用意图，改为在上述意图基础上叠加
        event_types 过滤。例如查"恒大集团的债务风险"用
        intent=ENTITY_OVERVIEW + entities=["恒大"] + event_types=["债务违约","监管处罚/合规调查"]；
        查担保关系用 RELATIONSHIP_QUERY 查询两实体间的关联路径。

        输出结构：
        - knowledge_units: 匹配的知识单元列表（含 text、entity_mentions、event_type 等）
        - entities: 涉及的实体画像（含 name、type、aliases）
        - event_clusters: 事件聚类（含 cluster_id、title、summary）
        - graph_data.clusters_overview: 聚类摘要列表，每个含 cluster_id、title、member_count，
          将 cluster_id 传给 expand_graph_detail 可获取完整图谱
        - total_count: 匹配的知识单元总数

        限制：
        - 实体名称优先使用中文；常见英文简称（BYD、CATL、NIO 等）可自动解析，
          冷门英文名可能解析不到，建议先转换为中文
        - 实体不在知识库中时返回空结果（不报错）
        - 知识库主要覆盖中国A股和港股上市公司、主要金融机构及宏观经济实体
        - 单次最多返回 top_k 条知识单元

        Args:
            entities: 实体名称列表，优先使用中文。支持公司简称（"小米集团"）、
                人名（"雷军"）、机构名（"证监会"）。
                常见英文简称如 "BYD"、"CATL" 可自动解析为对应中文实体；
                冷门英文名可能解析不到，建议先转换（如 "CATL" → "宁德时代"）。
            intent: 查询意图，决定检索策略和结果排序。可选值：
                - "ENTITY_OVERVIEW"（默认）：实体综合概览
                - "ENTITY_TIMELINE"：按时间排序的事件时间线
                - "RELATIONSHIP_QUERY"：两实体间关系路径，必须配合 target_entity
                - "COMPARATIVE_ANALYSIS"：多实体对比分析
                - "EVENT_ANALYSIS"：按事件类型筛选分析
                - "TOPIC_RESEARCH"：主题/产业链研究
                风险/担保/事件影响等场景不设专用意图，改用上述意图配合 event_types 过滤。
            time_range: 时间范围，格式 "START:END"（ISO 日期），两端必填，不支持开放区间；
                需要开放范围时请传一个足够远的结束日期（如当年年底）。
                例如 "2025-04-01:2026-05-24"。不传则不限时间。
            event_types: 按事件类型过滤。可传 canonical 英文值或中文别名（均会归一化）；
                无法识别的类型会返回错误并列出全部合法值，不会静默忽略。
                32 类闭集（不要用 announcement/other，已取消）：
                公司资本类：restructuring(重组/并购)、ipo(上市/增发)、
                    shareholding_change(增减持/大宗交易/配售)、equity_pledge(股权质押)、
                    dividend(分红/派息)、company_establishment(企业设立)、investment(投资/融资)
                公司经营类：financial_performance(财报/业绩)、product_launch(产品发布)、
                    business_strategy(企业战略)、executive_change(高管变动/实控人变动)
                公司风险类：debt_default(债务违约)、legal_proceeding(诉讼)、risk_warning(风险提示)
                市场分析类：stock_price_change(股价)、price_change(商品价格)、
                    sector_performance(板块表现)、market_analysis(市场分析)、
                    industry_analysis(行业分析)、rating_change(评级调整/目标价)
                监管类：regulatory_action(监管处罚)、sanction(制裁)、policy_announcement(政策发布)
                宏观类：economic_data(经济数据)、trade_data(贸易数据)
                影响因素类：diplomatic_event(外交)、military_action(军事)、political_statement(政治声明)
                关系/披露类：strategic_cooperation(战略合作/签约)、disclosure(澄清/回应/停牌)、
                    meeting(会议)、non_financial(明确非金融内容)
                例如 ["减持", "评级调整"] 或 ["shareholding_change", "rating_change"]。
            target_entity: 关系查询的目标实体（第二个实体），仅 intent="RELATIONSHIP_QUERY" 时有效。
                例如 entities=["比亚迪"], target_entity="特斯拉" 查询两者关系。
            hops: 图谱扩展跳数，必须在 1-5 范围内（越界返回错误）。
                1=仅直接关联，2-3=扩展到二/三度关联。默认 1。关系查询建议设 2-3。
            edge_role: 多跳遍历时按 INVOLVED_IN 边的角色剪枝。可选值：
                "subject"（事件主体/施动者）、"object"（事件客体/受动者）。
                不传 = 不剪枝（默认）。例如只跟主体走可大幅缩减热点实体的邻居。
            edge_scope: 多跳遍历时按 INVOLVED_IN 边的归属剪枝。可选值：
                "corporate"（公司自身的事）、"environment"（外部环境的事）。
                不传 = 不剪枝（默认）。
            top_k: 返回的最大知识单元数量。默认 20，必须在 1-100 范围内（越界返回错误）。
        """
        from src.graph.knowledge_retrieval import MAX_HOPS
        from src.orchestration.graph import run_pipeline
        from src.schemas.enums import UnitType, is_known_unit_type

        # Cheap validation on the event loop before occupying a worker thread.
        # 每个枚举/范围参数都返回可读错误并附合法值，让调用方 agent 能自我修正；
        # 校验必须与下游实现同源（is_known_unit_type 即 event_types 过滤的判定函数），
        # 避免出现"校验通过但过滤被静默丢弃"的缺口。
        try:
            parsed_intent = IntentType(intent)
        except ValueError:
            valid = ", ".join(t.value for t in IntentType)
            return {"error": f"Invalid intent '{intent}'. Valid values: {valid}"}

        if not 1 <= hops <= MAX_HOPS:
            return {"error": f"hops must be between 1 and {MAX_HOPS}, got {hops}"}

        if not 1 <= top_k <= 100:
            return {"error": f"top_k must be between 1 and 100, got {top_k}"}

        if event_types:
            unknown = [t for t in event_types if not is_known_unit_type(t)]
            if unknown:
                valid_types = ", ".join(t.value for t in UnitType)
                return {
                    "error": (
                        f"Unknown event types: {unknown}. "
                        f"Valid canonical values: {valid_types}. "
                        "Chinese aliases (e.g. '减持', '债务违约') are also accepted."
                    )
                }

        parsed_time_range = None
        if time_range:
            parts = time_range.split(":")
            if len(parts) != 2:
                return {
                    "error": "time_range must be START:END (ISO dates, both ends required)"
                }
            try:
                date.fromisoformat(parts[0])
                date.fromisoformat(parts[1])
            except ValueError:
                return {
                    "error": (
                        "time_range endpoints must be ISO dates "
                        f"(e.g. '2025-04-01:2026-05-24'), got '{time_range}'"
                    )
                }
            parsed_time_range = (parts[0], parts[1])

        structured_query = make_query(
            entities=entities,
            intent=parsed_intent,
            time_range=parsed_time_range,
            event_types=event_types,
            hops=hops,
            target_entity=target_entity,
            edge_role=edge_role,
            edge_scope=edge_scope,
        )

        # Offload the blocking retrieval to a bounded worker thread so the
        # event loop stays free for concurrent requests.
        return await run_sync_in_thread(
            lambda: run_pipeline(
                structured_query=structured_query,
                top_k=top_k,
                hops=hops,
                db_path=db_path,
            ).to_dict(),
            limiter=limiter,
        )

    @mcp.tool()
    async def expand_graph_detail(
        cluster_ids: list[str],
    ) -> dict[str, Any]:
        """展开图谱聚类的完整节点、边和路径详情。

        在 search_knowledge 返回后，从 graph_data.clusters_overview 中提取感兴趣的
        cluster_id，调用此工具获取该聚类的完整图谱结构（节点、边、路径）。

        何时使用：search_knowledge 的 graph_data.clusters_overview 中存在需要深入了解的聚类时。

        输出结构：
        - nodes: 聚类中的所有节点（实体和事件聚类）
        - edges: 节点间的关系边
        - paths: 实体间的关联路径
        - clusters_overview: 聚类摘要

        限制：
        - cluster_ids 必须来自 search_knowledge 的返回结果，不能凭空构造
        - 单次调用建议不超过 10 个 cluster_id
        - 不存在的 cluster_id 会被静默跳过

        Args:
            cluster_ids: 要展开的聚类 ID 列表，取自 search_knowledge 返回的
                graph_data.clusters_overview[].cluster_id。
                例如 ["cluster_abc123", "cluster_def456"]。
        """
        from src.orchestration.graph import expand_graph_detail as _expand

        return await run_sync_in_thread(
            lambda: _expand(cluster_ids=cluster_ids, db_path=db_path),
            limiter=limiter,
        )

    # ------------------------------------------------------------------
    # Market data tools（行情直连：纯 IO 走 async httpx，不占 to_thread
    # limiter；仅 SQLite 落库下放线程。见 marketdata-mcp-design.md 第六节）
    # ------------------------------------------------------------------

    @mcp.tool()
    async def search_stocks(
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """搜索股票与指数：代码、中文名、拼音缩写均可，返回标准候选列表。

        何时调用 / 意图选择指南：
        - 只知道公司名（如 '贵州茅台'），需要标准代码再查行情 → 先调本工具
        - get_stock_quotes / get_stock_history 返回 ambiguous 或 not_found 时，
          用本工具查看候选并消歧
        - 支持形式：6位A股代码（'600519'）、5位港股代码（'00700'）、中文名
          （精确或包含）、拼音缩写（'GZMT'）、带市场标识（'600519.SH'/'sh600519'）

        输出结构：
        - candidates: 候选列表，每项含 secid（标准标识，形如 '1.600519'/
          '116.00700'）、symbol、name、market（1=沪 0=深 116=港）、asset_type
        - note: 仅当本地主数据未命中、结果来自在线搜索时出现

        限制：
        - 覆盖A股、港股正股与常用指数（上证、深成、创业板、恒指、恒生科技），
          不含美股、ETF、权证
        - 单个代码可能对应多个标的（如 '000001' = 平安银行 + 上证指数），
        此时返回全部候选，不会自动选择

        Args:
            query: 搜索词，代码/中文名/拼音缩写/带市场标识的代码均可。
            limit: 返回候选数量上限，1-50，默认 10。
        """
        from src.marketdata import get_service

        if not query or not query.strip():
            return {"error": "query must be a non-empty string"}
        if not 1 <= limit <= 50:
            return {"error": f"limit must be between 1 and 50, got {limit}"}
        return await get_service().search_stocks(query.strip(), limit=limit)

    @mcp.tool()
    async def get_stock_quotes(
        symbols: list[str],
    ) -> dict[str, Any]:
        """批量查询股票/指数的实时行情（A股、港股、常用指数）。

        何时调用：
        - 用户问某股票现价、涨跌幅、当日高低开收 → 直接调用本工具
        - 不确定代码是否正确时，先调 search_stocks 消歧

        输出结构：
        - quotes: 行情列表（按输入顺序），每项含 price、change、change_pct、
          open、high、low、pre_close、volume、amount、market_time（交易所
          行情时间）、source、stale（是否来自本地旧快照）、as_of（仅 stale 时）
        - unresolved: 无法解析或上游无数据的 symbol，含 reason
          （ambiguous=歧义/not_found=未找到/no_data=上游无行情）与 candidates
        - degraded: true 表示至少一条来自旧快照（上游全挂时的显式降级，
          注意 as_of 时间）

        非交易时段返回最近收盘快照（看 market_time 判断新鲜度）。
        volume 单位：A股为手、港股为股；amount 为成交额（元/港元）。

        限制：
        - 单次最多 50 个 symbol
        - 名称歧义（如 '000001'）不会自动选择，进 unresolved，需先消歧
        - 数据源为公开行情接口，实时性约秒级；上游全挂时返回带 stale 标记
          的本地快照，绝不静默冒充新数据

        Args:
            symbols: 证券列表，每项可为代码（'600519'）、中文名（'贵州茅台'）
                或 search_stocks 返回的 secid。上限 50 个。
        """
        from src.marketdata import AllSourcesUnavailable, get_service

        if not symbols:
            return {"error": "symbols must be a non-empty list"}
        if len(symbols) > 50:
            return {"error": f"at most 50 symbols per call, got {len(symbols)}"}

        try:
            outcome = await get_service().get_quotes(symbols)
        except AllSourcesUnavailable as exc:
            return {
                "error": (
                    "所有行情源不可用，且本地无可用快照；请稍后重试。"
                    f"详情: {exc}"
                )
            }
        result: dict[str, Any] = {
            "quotes": outcome.quotes,
            "quote_count": len(outcome.quotes),
        }
        if outcome.unresolved:
            result["unresolved"] = outcome.unresolved
        if outcome.degraded:
            result["degraded"] = True
            result["degraded_note"] = (
                "部分或全部行情来自本地旧快照（见各条 as_of），上游行情源当前不可用"
            )
        return result

    @mcp.tool()
    async def get_stock_history(
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        adjust: str = "qfq",
        limit: int = 500,
    ) -> dict[str, Any]:
        """查询股票/指数的历史日K线（默认前复权）。

        何时调用：
        - 用户要看某段时间的股价走势、区间涨跌幅、历史高低点 → 调用本工具
        - 只需要最新报价时用 get_stock_quotes，不要拉全量历史

        输出结构：
        - secid、adjust、count、first_date、last_date
        - bars: 日K数组（升序），每项含 date、open、high、low、close、
          volume（A股:手/港股:股）、amount

        限制：
        - 一次最多返回 limit 根（默认 500，约两年日线），超出时返回最近的
          limit 根；需要更长历史请分段调用
        - 复权仅支持前复权（qfq）；前复权价格在分红除权后会整段调整，
          已自动检测并重建缓存
        - 含当日未收盘的实时K线（盘中调用时当日 close 为最新价）
        - 覆盖范围同 get_stock_quotes（A股、港股、常用指数）

        Args:
            symbol: 代码/中文名/secid，同 get_stock_quotes。歧义时报错并
                返回 candidates，请先调 search_stocks 消歧。
            start_date: 起始日期（ISO，如 '2026-01-01'），可省略。
            end_date: 结束日期（ISO），可省略，默认至今。
            adjust: 复权方式，当前仅支持 'qfq'（前复权）。
            limit: 最多返回的K线数量，1-500，默认 500。
        """
        import dateutil.parser as dparser

        from src.marketdata import get_service

        if adjust != "qfq":
            return {
                "error": (
                    f"Unsupported adjust: {adjust!r}. Only 'qfq' "
                    "(前复权) is supported in the current version."
                )
            }
        if not 1 <= limit <= 500:
            return {"error": f"limit must be between 1 and 500, got {limit}"}
        for label, value in (("start_date", start_date), ("end_date", end_date)):
            if value is not None:
                try:
                    dparser.isoparse(value)
                except ValueError:
                    return {
                        "error": (
                            f"{label} must be an ISO date "
                            f"(e.g. '2026-01-01'), got {value!r}"
                        )
                    }

        return await get_service().get_history(
            symbol, start=start_date, end=end_date, limit=limit
        )

    return mcp
