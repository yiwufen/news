"""
Pytest fixtures for stable temporary directories on Windows.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def tmp_path() -> Path:
    path = Path(".tmp") / "test-dirs" / f"case-{uuid4().hex[:12]}"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
