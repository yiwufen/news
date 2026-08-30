"""
OpenAICompatEmbedding client tests (mocked transport — never real network):
fail-fast on missing key (no fallback to SILICONFLOW_API_KEY), request shape,
and MAX_BATCH chunking.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.retrieval.embedding import MAX_BATCH, OpenAICompatEmbedding


def _install_transport(monkeypatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    monkeypatch.setattr(httpx, "post", client.post)
    monkeypatch.setattr("src.retrieval.embedding.time.sleep", lambda _s: None)
    return requests


def _make_embedding(monkeypatch) -> OpenAICompatEmbedding:
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "BAAI/bge-m3")
    return OpenAICompatEmbedding()


def _echo_handler(request: httpx.Request) -> httpx.Response:
    """Return one vector per input; the vector encodes the input's position
    (parsed from "t<n>" text) so cross-chunk ordering is verifiable.
    Data is reversed to exercise the client's index-based sorting."""
    body = json.loads(request.read())
    data = [
        {"index": i, "embedding": [float(body["input"][i][1:])]}
        for i in range(len(body["input"]))
    ]
    data.reverse()
    return httpx.Response(200, json={"data": data})


def test_missing_key_raises_even_with_siliconflow_key(monkeypatch) -> None:
    # The embedding key is explicit-only: an unrelated SILICONFLOW_API_KEY
    # (used by the reranker) must NOT be picked up as a fallback.
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-other")

    with pytest.raises(ValueError, match="OPENAI_EMBEDDING_API_KEY"):
        OpenAICompatEmbedding()


def test_request_shape(monkeypatch) -> None:
    requests = _install_transport(monkeypatch, _echo_handler)
    embedding = _make_embedding(monkeypatch)

    vectors = embedding.embed(["t0"])

    assert vectors == [[0.0]]
    assert len(requests) == 1
    body = json.loads(requests[0].read())
    assert body == {"model": "BAAI/bge-m3", "input": ["t0"]}
    assert requests[0].url.host == "api.siliconflow.cn"
    assert requests[0].url.path == "/v1/embeddings"
    assert requests[0].headers["Authorization"] == "Bearer sk-test"


def test_empty_input_short_circuits(monkeypatch) -> None:
    requests = _install_transport(monkeypatch, _echo_handler)
    embedding = _make_embedding(monkeypatch)

    assert embedding.embed([]) == []
    assert requests == []


def test_chunks_oversized_batch_and_preserves_order(monkeypatch) -> None:
    requests = _install_transport(monkeypatch, _echo_handler)
    embedding = _make_embedding(monkeypatch)

    texts = [f"t{i}" for i in range(MAX_BATCH + 5)]
    vectors = embedding.embed(texts)

    assert [v[0] for v in vectors] == [float(i) for i in range(MAX_BATCH + 5)]
    assert len(requests) == 2
    first = json.loads(requests[0].read())["input"]
    second = json.loads(requests[1].read())["input"]
    assert len(first) == MAX_BATCH
    assert len(second) == 5
    assert second[0] == f"t{MAX_BATCH}"


def test_retries_then_raises(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    _install_transport(monkeypatch, handler)
    embedding = _make_embedding(monkeypatch)

    with pytest.raises(RuntimeError, match="after 3 retries"):
        embedding.embed(["t0"])
    assert calls["n"] == 3
