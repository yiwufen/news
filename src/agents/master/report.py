"""
报告生成模块

生成带溯源的风险分析报告。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RiskConclusion:
    """风险结论"""

    conclusion: str
    source_particle_ids: list[str]
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "conclusion": self.conclusion,
            "source_particle_ids": self.source_particle_ids,
            "confidence": self.confidence,
        }


@dataclass
class ConflictInfo:
    """冲突情报信息"""

    description: str
    conflicting_particles: list[str]
    suggested_resolution: str | None = None

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "conflicting_particles": self.conflicting_particles,
            "suggested_resolution": self.suggested_resolution,
        }


@dataclass
class RiskReport:
    """风险分析报告"""

    report_id: str
    generated_at: datetime
    target_entity: str
    risk_level: str
    risk_score: float
    conclusions: list[RiskConclusion] = field(default_factory=list)
    conflicts: list[ConflictInfo] = field(default_factory=list)
    risk_paths: list[dict[str, Any]] = field(default_factory=list)
    source_particles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "target_entity": self.target_entity,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "conclusions": [c.to_dict() for c in self.conclusions],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "risk_paths": self.risk_paths,
            "source_particles": self.source_particles,
        }

    def to_markdown(self) -> str:
        """生成 Markdown 格式报告"""
        lines = [
            f"# 风险分析报告",
            "",
            f"**报告ID**: {self.report_id}",
            f"**生成时间**: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**目标实体**: {self.target_entity}",
            f"**风险等级**: {self.risk_level}",
            f"**风险分值**: {self.risk_score:.3f}",
            "",
            "---",
            "",
            "## 风险结论",
            "",
        ]

        for i, conclusion in enumerate(self.conclusions, 1):
            sources = ", ".join(f"[Source: {sid}]" for sid in conclusion.source_particle_ids)
            lines.append(f"{i}. {conclusion.conclusion} {sources}")
            lines.append("")

        if self.conflicts:
            lines.extend([
                "---",
                "",
                "## 冲突情报",
                "",
            ])
            for conflict in self.conflicts:
                lines.append(f"- **冲突**: {conflict.description}")
                lines.append(f"  - 涉及情报: {', '.join(conflict.conflicting_particles)}")
                if conflict.suggested_resolution:
                    lines.append(f"  - 建议: {conflict.suggested_resolution}")
                lines.append("")

        lines.extend([
            "---",
            "",
            "## 风险传导路径",
            "",
        ])

        for path in self.risk_paths:
            chain = " → ".join(path.get("chain", []))
            lines.append(f"- {chain} (风险分值: {path.get('weighted_risk', 0):.3f})")

        lines.extend([
            "",
            "---",
            "",
            f"*来源情报微粒: {', '.join(self.source_particles)}*",
        ])

        return "\n".join(lines)


class ReportGenerator:
    """报告生成器"""

    @classmethod
    def generate(
        cls,
        target_entity: str,
        risk_level: str,
        risk_score: float,
        conclusions: list[dict],
        conflicts: list[dict] | None = None,
        risk_paths: list[dict] | None = None,
        source_particles: list[str] | None = None,
    ) -> RiskReport:
        """生成风险报告

        Args:
            target_entity: 目标实体
            risk_level: 风险等级
            risk_score: 风险分值
            conclusions: 结论列表
            conflicts: 冲突信息
            risk_paths: 风险路径
            source_particles: 来源情报微粒 ID

        Returns:
            风险报告
        """
        import uuid

        report = RiskReport(
            report_id=f"rpt_{uuid.uuid4().hex[:12]}",
            generated_at=datetime.now(),
            target_entity=target_entity,
            risk_level=risk_level,
            risk_score=risk_score,
            conclusions=[
                RiskConclusion(
                    conclusion=c["conclusion"],
                    source_particle_ids=c.get("source_particle_ids", []),
                    confidence=c.get("confidence", 1.0),
                )
                for c in conclusions
            ],
            conflicts=[
                ConflictInfo(
                    description=conf["description"],
                    conflicting_particles=conf.get("conflicting_particles", []),
                    suggested_resolution=conf.get("suggested_resolution"),
                )
                for conf in (conflicts or [])
            ],
            risk_paths=risk_paths or [],
            source_particles=source_particles or [],
        )

        return report
