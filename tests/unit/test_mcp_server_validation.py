"""search_knowledge 参数校验回路测试。

校验发生在事件循环上、进入工作线程之前。所有非法参数都应返回
``{"error": ...}`` 并附带合法值信息，供调用方 agent 自我修正——
特别是 event_types：下游 ``expand_event_types`` 会静默丢弃未知类型
导致过滤蒸发，MCP 层校验必须在这一步之前拦截。
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest


@pytest.fixture()
def search_tool(monkeypatch):
    """注册好的 search_knowledge 工具，run_pipeline 打桩防真实检索。"""
    from src.mcp_server import create_server

    fake_pipeline = mock.MagicMock()
    fake_pipeline.to_dict.return_value = {"ok": True}
    monkeypatch.setattr(
        "src.orchestration.graph.run_pipeline",
        lambda **kwargs: fake_pipeline,
    )
    server = create_server()
    return server._tool_manager.get_tool("search_knowledge")


def _call(tool, **kwargs):
    return asyncio.run(tool.fn(**kwargs))


def test_unknown_event_types_return_error_with_valid_values(search_tool):
    result = _call(search_tool, entities=["比亚迪"], event_types=["不存在的类型"])
    assert "error" in result
    assert "不存在的类型" in result["error"]
    # 错误信息包含合法 canonical 值，供 agent 自我修正
    assert "financial_performance" in result["error"]
    assert "restructuring" in result["error"]


def test_partial_unknown_event_types_rejected(search_tool):
    """混入一个未知类型也应整体报错，避免过滤被静默收窄或蒸发。"""
    result = _call(search_tool, entities=["比亚迪"], event_types=["减持", "zzz_unknown"])
    assert "error" in result
    assert "zzz_unknown" in result["error"]


def test_known_chinese_alias_and_canonical_pass(search_tool):
    result = _call(
        search_tool, entities=["比亚迪"], event_types=["减持", "rating_change"]
    )
    assert result == {"ok": True}


def test_hops_out_of_range_returns_error(search_tool):
    for bad_hops in (0, 6):
        result = _call(search_tool, entities=["比亚迪"], hops=bad_hops)
        assert "error" in result, f"hops={bad_hops} 应报错"
        assert "hops" in result["error"]


def test_top_k_out_of_range_returns_error(search_tool):
    for bad_top_k in (0, 101):
        result = _call(search_tool, entities=["比亚迪"], top_k=bad_top_k)
        assert "error" in result, f"top_k={bad_top_k} 应报错"
        assert "top_k" in result["error"]


def test_time_range_missing_end_returns_error(search_tool):
    result = _call(search_tool, entities=["比亚迪"], time_range="2025-04-01:")
    assert "error" in result


def test_time_range_non_iso_returns_error(search_tool):
    result = _call(
        search_tool, entities=["比亚迪"], time_range="2025/04/01:2026-05-24"
    )
    assert "error" in result


def test_valid_time_range_passes(search_tool):
    result = _call(
        search_tool, entities=["比亚迪"], time_range="2025-04-01:2026-05-24"
    )
    assert result == {"ok": True}
