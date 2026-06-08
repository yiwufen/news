"""MCP server exposing knowledge-cli as remote tools via Streamable HTTP."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.paths import DEFAULT_DB_PATH
from src.schemas.query import IntentType, make_query


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
    """Create a configured FastMCP server with all tools registered."""

    mcp = FastMCP(
        name="knowledge-cli",
        instructions=(
            "金融知识检索服务，主要覆盖中国A股和港股市场。\n"
            "\n"
            "提供两层检索工作流：\n"
            "1. search_knowledge：检索实体、事件和关系。返回知识单元、实体画像、事件聚类和图谱概览。\n"
            "2. expand_graph_detail：展开图谱聚类的完整节点/边/路径详情。需要 search_knowledge 返回的 cluster_id。\n"
            "\n"
            "典型工作流：先调用 search_knowledge，从返回的 graph_data.clusters_overview 中提取感兴趣的 "
            "cluster_id，再调用 expand_graph_detail 获取完整图谱结构。\n"
            "\n"
            "实体名称必须使用中文（如 '比亚迪'、'宁德时代'），不支持英文简称（如 'BYD'）。"
        ),
        host=host,
        port=port,
        stateless_http=True,
    )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool()
    def search_knowledge(
        entities: list[str],
        intent: str = "ENTITY_OVERVIEW",
        time_range: str | None = None,
        event_types: list[str] | None = None,
        target_entity: str | None = None,
        hops: int = 1,
        top_k: int = 20,
    ) -> dict[str, Any]:
        """从金融知识库中检索实体、事件和关系。支持9种查询意图，返回知识单元、实体画像、事件聚类和图谱概览。

        何时调用 / 意图选择指南：
        - 用户问某公司/人物的概况或最新动态 → ENTITY_OVERVIEW（默认）
        - 用户要求按时间线梳理某实体的事件 → ENTITY_TIMELINE
        - 用户问两个实体之间的关系（如"比亚迪和特斯拉的合作"）→ RELATIONSHIP_QUERY（必须同时设置 target_entity）
        - 用户要求比较多个实体（如"比亚迪和特斯拉的业绩对比"）→ COMPARATIVE_ANALYSIS
        - 用户问某类事件（如"最近的并购事件"）→ EVENT_ANALYSIS
        - 用户问风险因素（如"恒大集团的债务风险"）→ RISK_ASSESSMENT
        - 用户研究某个主题/产业链（如"新能源车产业链"）→ TOPIC_RESEARCH
        - 用户问某事件的影响范围 → EVENT_IMPACT_ANALYSIS
        - 用户问担保关系 → GUARANTEE_ANALYSIS

        输出结构：
        - knowledge_units: 匹配的知识单元列表（含 text、entity_mentions、event_type 等）
        - entities: 涉及的实体画像（含 name、type、aliases）
        - event_clusters: 事件聚类（含 cluster_id、title、summary）
        - graph_data.clusters_overview: 聚类摘要列表，每个含 cluster_id、title、member_count，
          将 cluster_id 传给 expand_graph_detail 可获取完整图谱
        - total_count: 匹配的知识单元总数

        限制：
        - 实体名称必须使用中文，不支持英文简称
        - 实体不在知识库中时返回空结果（不报错）
        - 知识库主要覆盖中国A股和港股上市公司、主要金融机构及宏观经济实体
        - 单次最多返回 top_k 条知识单元

        Args:
            entities: 实体名称列表，使用中文名称。支持公司简称（"小米集团"）、
                人名（"雷军"）、机构名（"证监会"）。
                不支持英文简称如 "BYD"，需转换为中文 "比亚迪"。
            intent: 查询意图，决定检索策略和结果排序。可选值：
                - "ENTITY_OVERVIEW"（默认）：实体综合概览
                - "ENTITY_TIMELINE"：按时间排序的事件时间线
                - "RELATIONSHIP_QUERY"：两实体间关系路径，必须配合 target_entity
                - "COMPARATIVE_ANALYSIS"：多实体对比分析
                - "EVENT_ANALYSIS"：按事件类型筛选分析
                - "RISK_ASSESSMENT"：风险因素评估
                - "TOPIC_RESEARCH"：主题/产业链研究
                - "EVENT_IMPACT_ANALYSIS"：事件影响范围分析
                - "GUARANTEE_ANALYSIS"：担保关系分析
            time_range: 时间范围，格式 "START:END"（ISO日期）。
                例如 "2025-04-01:2026-05-24"。不传则不限时间。
            event_types: 按事件类型过滤。可选值：
                "政策制裁/出口管制"、"股市波动/市场异动"、"企业并购/重组"、
                "供应链中断/调整"、"财报发布/业绩预告"、"监管处罚/合规调查"、
                "关税调整/贸易协定"、"高管变动/人事调整"、"IPO/融资事件"、
                "地缘政治影响"。
                例如 ["财报发布/业绩预告", "高管变动/人事调整"]。
            target_entity: 关系查询的目标实体（第二个实体），仅 intent="RELATIONSHIP_QUERY" 时有效。
                例如 entities=["比亚迪"], target_entity="特斯拉" 查询两者关系。
            hops: 图谱扩展跳数（1-5）。1=仅直接关联，2-3=扩展到二/三度关联。
                默认 1。关系查询建议设 2-3。
            top_k: 返回的最大知识单元数量。默认 20，范围 1-100。
        """
        from src.orchestration.graph import run_pipeline

        try:
            parsed_intent = IntentType(intent)
        except ValueError:
            valid = ", ".join(t.value for t in IntentType)
            return {"error": f"Invalid intent '{intent}'. Valid values: {valid}"}

        parsed_time_range = None
        if time_range:
            parts = time_range.split(":")
            if len(parts) != 2:
                return {"error": "time_range must be START:END (ISO dates)"}
            parsed_time_range = (parts[0], parts[1])

        structured_query = make_query(
            entities=entities,
            intent=parsed_intent,
            time_range=parsed_time_range,
            event_types=event_types,
            hops=hops,
            target_entity=target_entity,
        )

        result = run_pipeline(
            structured_query=structured_query,
            top_k=top_k,
            hops=hops,
            db_path=db_path,
        )

        return result.to_dict()

    @mcp.tool()
    def expand_graph_detail(
        cluster_ids: list[str],
    ) -> dict[str, Any]:
        """展开图谱聚类的完整节点、边和路径详情。

        在 search_knowledge 返回后，从 graph_data.clusters_overview 中提取感兴趣的
        cluster_id，调用此工具获取该聚类的完整图谱结构（节点、边、路径）。

        何时使用：search_knowledge 的 graph_data.clusters_overview 中存在需要深入了解的聚类时。

        输出结构：
        - nodes: 聚类中的所有节点（实体和知识单元）
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

        return _expand(cluster_ids=cluster_ids, db_path=db_path)

    return mcp
