"""
Worker Agent 模块

情报微粒提取器。
"""

from src.agents.worker.agent import WorkerAgent
from src.agents.worker.prompts import (
    SYSTEM_PROMPT,
    build_batch_extraction_prompt,
    build_extraction_prompt,
    compute_slice_window,
)
from src.agents.worker.tools import EXTRACTION_TOOL_SCHEMA

__all__ = [
    "WorkerAgent",
    "SYSTEM_PROMPT",
    "build_extraction_prompt",
    "build_batch_extraction_prompt",
    "compute_slice_window",
    "EXTRACTION_TOOL_SCHEMA",
]
