"""Embedding provider for dense retrieval.

Uses OpenAI-compatible API configured via environment variables:
  OPENAI_EMBEDDING_BASE_URL
  OPENAI_EMBEDDING_API_KEY
  OPENAI_EMBEDDING_MODEL
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dim(self) -> int: ...

    @property
    def model_name(self) -> str: ...


class OpenAICompatEmbedding:
    """Embedding via OpenAI-compatible API (OpenRouter, etc.).

    Uses httpx directly instead of the OpenAI SDK to avoid
    response-parsing incompatibilities with non-OpenAI providers.
    """

    def __init__(self) -> None:
        self._base_url = (
            os.environ.get("OPENAI_EMBEDDING_BASE_URL") or ""
        ).rstrip("/")
        self._api_key = os.environ.get("OPENAI_EMBEDDING_API_KEY", "")
        self._model = os.environ.get(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )

        if not self._api_key:
            raise ValueError("OPENAI_EMBEDDING_API_KEY not configured")

        self._dim: int | None = None

    def embed(
        self, texts: list[str], *, retries: int = 3, base_delay: float = 2.0
    ) -> list[list[float]]:
        if not texts:
            return []
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = httpx.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": texts},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                vectors = [
                    d["embedding"] for d in sorted(data, key=lambda d: d["index"])
                ]
                if self._dim is None and vectors:
                    self._dim = len(vectors[0])
                return vectors
            except (httpx.HTTPError, KeyError) as exc:
                last_exc = exc
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Embedding attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
        raise RuntimeError(f"Embedding failed after {retries} retries") from last_exc

    @property
    def dim(self) -> int:
        if self._dim is None:
            sample = self.embed(["test"])
            self._dim = len(sample[0])
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model
