"""Reranker provider for post-fusion precision re-ranking.

Uses the SiliconFlow rerank API (dedicated /rerank endpoint, NOT the
OpenAI-compatible chat interface), configured via environment variables:

  SILICONFLOW_API_KEY        (required)
  SILICONFLOW_BASE_URL       default https://api.siliconflow.cn/v1
  SILICONFLOW_RERANK_MODEL   default BAAI/bge-reranker-v2-m3
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


@runtime_checkable
class RerankProvider(Protocol):
    """Protocol for rerank providers."""

    def rerank(
        self, query: str, documents: list[str]
    ) -> list[tuple[int, float]]:
        """Return (document_index, relevance_score) sorted by score desc."""
        ...


class SiliconFlowReranker:
    """Rerank via SiliconFlow's dedicated /rerank endpoint.

    Follows the OpenAICompatEmbedding client pattern: direct httpx call,
    Bearer auth, exponential-backoff retries, RuntimeError on exhaustion.
    """

    def __init__(self) -> None:
        self._base_url = (
            os.environ.get("SILICONFLOW_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._api_key = os.environ.get("SILICONFLOW_API_KEY", "")
        self._model = os.environ.get(
            "SILICONFLOW_RERANK_MODEL", DEFAULT_RERANK_MODEL
        )

        if not self._api_key:
            raise ValueError("SILICONFLOW_API_KEY not configured")

    def rerank(
        self, query: str, documents: list[str], *, retries: int = 3, base_delay: float = 2.0
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = httpx.post(
                    f"{self._base_url}/rerank",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "query": query,
                        "documents": documents,
                        "return_documents": False,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                results = resp.json()["results"]
                ranked = [
                    (int(item["index"]), float(item["relevance_score"]))
                    for item in results
                ]
                ranked.sort(key=lambda pair: pair[1], reverse=True)
                return ranked
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                last_exc = exc
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Rerank attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError(f"Rerank failed after {retries} retries") from last_exc

    @property
    def model_name(self) -> str:
        return self._model


def try_create_reranker() -> SiliconFlowReranker | None:
    """Create the reranker, or return None when unconfigured/disabled.

    Mirrors indexing.try_create_vector_index: absence of configuration is a
    supported degraded mode (weighted-fusion ordering is used instead), not an
    error. KNOWLEDGE_RERANK_DISABLED=1 forces the degraded mode for
    deterministic eval gates and tests.
    """
    if os.environ.get("KNOWLEDGE_RERANK_DISABLED", "") == "1":
        return None
    if not os.environ.get("SILICONFLOW_API_KEY"):
        return None
    try:
        return SiliconFlowReranker()
    except Exception:
        logger.warning("Reranker creation failed", exc_info=True)
        return None
