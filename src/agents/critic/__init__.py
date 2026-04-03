"""
Critic Agent 模块

事实核查与熔断机制。
"""

from src.agents.critic.agent import (
    CriticAgent,
    IssueType,
    VerificationIssue,
    VerificationResult,
)
from src.agents.critic.prompts import SYSTEM_PROMPT, build_verification_prompt

__all__ = [
    "CriticAgent",
    "IssueType",
    "VerificationIssue",
    "VerificationResult",
    "SYSTEM_PROMPT",
    "build_verification_prompt",
]
