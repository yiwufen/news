"""
Pytest fixtures for stable temporary directories on Windows.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

# Tests must stay hermetic: never auto-create the SiliconFlow reranker from a
# developer's real .env (network calls in unit tests). Tests that exercise the
# reranker inject fakes explicitly via KnowledgeSearcher(reranker=...).
os.environ.setdefault("KNOWLEDGE_RERANK_DISABLED", "1")


@pytest.fixture
def tmp_path() -> Path:
    path = Path(".tmp") / "test-dirs" / f"case-{uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
