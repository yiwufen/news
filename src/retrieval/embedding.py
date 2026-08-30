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

# SiliconFlow's /embeddings endpoint accepts at most 32 input strings per
# request; other OpenAI-compatible providers impose similar caps.
MAX_BATCH = 32

# Per-minute rate limits (SiliconFlow free tier: 2000 RPM / 500K TPM) need a
# full-window cooldown; the seconds-level backoff for transient errors cannot
# outlast them, so 429 gets its own longer wait and attempt budget.
RATE_LIMIT_COOLDOWN = 60.0
MAX_RATE_LIMIT_WAITS = 10


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
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            chunk = texts[start : start + MAX_BATCH]
            vectors.extend(
                self._embed_chunk(chunk, retries=retries, base_delay=base_delay)
            )
        return vectors

    def _embed_chunk(
        self, texts: list[str], *, retries: int, base_delay: float
    ) -> list[list[float]]:
        last_exc: Exception | None = None
        attempts = 0
        rate_limit_waits = 0
        while attempts < retries:
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
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code == 429
                    and rate_limit_waits < MAX_RATE_LIMIT_WAITS
                ):
                    rate_limit_waits += 1
                    retry_after = exc.response.headers.get("Retry-After", "")
                    cooldown = (
                        float(retry_after)
                        if retry_after.isdigit()
                        else RATE_LIMIT_COOLDOWN
                    )
                    cooldown = max(cooldown, RATE_LIMIT_COOLDOWN)
                    logger.warning(
                        "Embedding rate-limited (429) — cooldown %.0fs (wait %d/%d)",
                        cooldown,
                        rate_limit_waits,
                        MAX_RATE_LIMIT_WAITS,
                    )
                    time.sleep(cooldown)
                    continue
                attempts += 1
                delay = base_delay * (2 ** (attempts - 1))
                logger.warning(
                    "Embedding attempt %d/%d failed: %s — retrying in %.1fs",
                    attempts,
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
