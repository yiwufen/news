"""
Master Agent 模块

风险穿透分析与报告生成。
"""

from src.agents.master.agent import MasterAgent
from src.agents.master.prompts import SYSTEM_PROMPT, build_analysis_prompt
from src.agents.master.report import ReportGenerator, RiskReport

__all__ = [
    "MasterAgent",
    "ReportGenerator",
    "RiskReport",
    "SYSTEM_PROMPT",
    "build_analysis_prompt",
]
