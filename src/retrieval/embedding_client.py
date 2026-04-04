"""
Embedding client abstractions and OpenAI-compatible implementation.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, cast
from urllib import error, request


DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_API_KEY_ENV = "OPENAI_EMBEDDING_API_KEY"
EMBEDDING_BASE_URL_ENV = "OPENAI_EMBEDDING_BASE_URL"
SHARED_API_KEY_ENV = "OPENAI_API_KEY"


class EmbeddingClient(Protocol):
    """Small embeddng interface for retrieval and indexing."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


class OpenAIEmbeddingClient:
    """OpenAI-compatible embeddings API client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get(EMBEDDING_API_KEY_ENV) or os.environ.get(SHARED_API_KEY_ENV)
        self.base_url = (base_url or os.environ.get(EMBEDDING_BASE_URL_ENV) or DEFAULT_EMBEDDING_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("OPENAI_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def require_configured(self) -> None:
        if not self.api_key:
            raise ValueError(
                f"{EMBEDDING_API_KEY_ENV} or {SHARED_API_KEY_ENV} environment variable is not set"
            )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.require_configured()
        if not texts:
            return []

        payload = json.dumps(
            {
                "model": self.model,
                "input": texts,
            }
        ).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"embedding API request failed with status {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"embedding API request failed: {exc.reason}") from exc

        data = response_data.get("data")
        if not isinstance(data, list):
            raise RuntimeError("embedding API response is missing data array")

        ordered = sorted(
            (
                (
                    int(item.get("index", index)),
                    item.get("embedding"),
                )
                for index, item in enumerate(data)
                if isinstance(item, dict)
            ),
            key=lambda item: item[0],
        )
        embeddings = [cast(list[float], embedding) for _, embedding in ordered]
        if len(embeddings) != len(texts):
            raise RuntimeError("embedding API returned mismatched embedding count")
        for embedding in embeddings:
            if not embedding:
                raise RuntimeError("embedding API returned an empty embedding")
        return embeddings
