"""
Critic Agent - 事实核查

按 .claude/rules/02-prompts.md 定义的 Critic Agent 规范。
"""

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from anthropic import Anthropic

from src.agents.critic.prompts import SYSTEM_PROMPT, build_verification_prompt
from src.schemas import IntelligenceParticle


class IssueType(Enum):
    """问题类型"""

    MISSING_SOURCE = "缺少来源"
    CONTRADICTION = "内容矛盾"
    TEMPORAL_ERROR = "时间线错误"
    HALLUCINATION = "幻觉内容"


@dataclass
class VerificationIssue:
    """核查发现的问题"""

    type: IssueType
    description: str
    location: str
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "description": self.description,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class VerificationResult:
    """核查结果"""

    passed: bool
    issues: list[VerificationIssue]
    suggestions: list[str]
    retry_count: int = 0

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "suggestions": self.suggestions,
            "retry_count": self.retry_count,
        }


class CriticAgent:
    """Critic Agent

    职责：
    1. 验证报告的准确性
    2. 驳回无依据的"幻觉"结论
    3. 实现死循环熔断（max_retries=2）
    """

    MAX_RETRIES = 2  # 按 CLAUDE.md 规定的熔断上限

    def __init__(self):
        self._init_llm_client()

    def _init_llm_client(self) -> None:
        """初始化 LLM 客户端"""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        base_url = os.environ.get("ANTHROPIC_API_BASE_URL")
        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = os.environ.get("ANTHROPIC_MODEL") or "glm-5"
        self.max_tokens = 2048

    def verify(
        self,
        report: dict,
        particles: list[IntelligenceParticle],
    ) -> VerificationResult:
        """核查报告

        Args:
            report: 待核查的报告
            particles: 原始情报微粒

        Returns:
            核查结果
        """
        # 转换情报微粒为字典
        particles_data = [p.model_dump() for p in particles]

        # 调用 LLM 进行核查
        user_prompt = build_verification_prompt(report, particles_data)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # 解析响应
        content = ""
        if response.content:
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    content += text

        try:
            result = json.loads(content) if content else {}
        except json.JSONDecodeError:
            # 解析失败，默认通过
            return VerificationResult(
                passed=True,
                issues=[],
                suggestions=["核查结果解析失败，默认通过"],
            )

        # 构建问题列表
        issues: list[VerificationIssue] = []
        for issue in result.get("issues", []):
            try:
                issue_type = IssueType(issue.get("type", "MISSING_SOURCE"))
            except ValueError:
                issue_type = IssueType.HALLUCINATION

            issues.append(
                VerificationIssue(
                    type=issue_type,
                    description=issue.get("description", ""),
                    location=issue.get("location", ""),
                    suggestion=issue.get("suggestion"),
                )
            )

        return VerificationResult(
            passed=result.get("passed", True),
            issues=issues,
            suggestions=result.get("suggestions", []),
        )

    def verify_with_retry(
        self,
        report: dict,
        particles: list[IntelligenceParticle],
        on_retry: "Callable[[VerificationResult], dict | None] | None" = None,
    ) -> VerificationResult:
        """带熔断机制的核查

        最多重试 MAX_RETRIES 次（默认 2 次）。
        超过次数依然不通过的，按"置信度不足"降级输出。

        Args:
            report: 待核查的报告
            particles: 原始情报微粒
            on_retry: 重试回调函数

        Returns:
            核查结果
        """
        result: VerificationResult | None = None

        for retry_count in range(self.MAX_RETRIES + 1):
            result = self.verify(report, particles)
            result.retry_count = retry_count

            if result.passed:
                return result

            # 未通过，检查是否需要重试
            if retry_count < self.MAX_RETRIES and on_retry:
                # 调用回调进行修正
                new_report = on_retry(result)
                if new_report is None:
                    break
                report = new_report

        # 超过重试次数，降级输出
        if result and not result.passed:
            result.suggestions.append(
                f"已达到最大重试次数 ({self.MAX_RETRIES})，按置信度不足降级输出"
            )

        return result or VerificationResult(
            passed=True,
            issues=[],
            suggestions=["核查流程异常，默认通过"],
        )

    def check_hallucination(
        self,
        conclusion: str,
        source_particle_ids: list[str],
        particles: list[IntelligenceParticle],
    ) -> VerificationIssue | None:
        """检查结论是否为幻觉

        Args:
            conclusion: 结论内容
            source_particle_ids: 声称的来源 ID
            particles: 实际的情报微粒

        Returns:
            如发现问题，返回 VerificationIssue；否则返回 None
        """
        particle_ids = {p.id for p in particles}

        # 检查来源 ID 是否存在
        invalid_ids = [sid for sid in source_particle_ids if sid not in particle_ids]
        if invalid_ids:
            return VerificationIssue(
                type=IssueType.MISSING_SOURCE,
                description=f"结论引用了不存在的情报微粒: {invalid_ids}",
                location=conclusion,
                suggestion="请核实来源 ID 或移除该结论",
            )

        # 检查是否有来源支撑
        if not source_particle_ids:
            return VerificationIssue(
                type=IssueType.HALLUCINATION,
                description="结论缺少来源支撑",
                location=conclusion,
                suggestion="请添加来源 Particle ID 或移除该结论",
            )

        return None

    def check_temporal_logic(
        self,
        event_time: str,
        conclusion_time: str,
    ) -> VerificationIssue | None:
        """检查时间线逻辑

        禁止使用发生时间在 T2 的事件去预警 T1 的风险。

        Args:
            event_time: 事件发生时间
            conclusion_time: 结论时间

        Returns:
            如发现问题，返回 VerificationIssue；否则返回 None
        """
        from datetime import datetime

        try:
            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            conclusion_dt = datetime.fromisoformat(conclusion_time.replace("Z", "+00:00"))

            if event_dt > conclusion_dt:
                return VerificationIssue(
                    type=IssueType.TEMPORAL_ERROR,
                    description=f"时间线错误：事件 ({event_time}) 晚于结论时间 ({conclusion_time})",
                    location="时间线",
                    suggestion="请调整时间线或移除该结论",
                )
        except ValueError:
            pass

        return None
