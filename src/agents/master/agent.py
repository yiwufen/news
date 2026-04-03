"""
Master Agent - 风险穿透分析

按 .claude/rules/02-prompts.md 定义的 Master Agent 规范。
"""

import json
import os
from typing import Any

from anthropic import Anthropic

from src.agents.master.prompts import SYSTEM_PROMPT, build_analysis_prompt
from src.agents.master.report import ReportGenerator, RiskReport
from src.graph import GraphQueries
from src.risk import RiskCalculator, RiskPath
from src.schemas import IntelligenceParticle


class MasterAgent:
    """Master Agent

    职责：
    1. 接收分析师查询
    2. 执行 Cypher 查询，向下搜索 3 层关系路径
    3. 计算风险传导分值
    4. 生成带溯源的分析报告
    """

    def __init__(
        self,
        graph_queries: GraphQueries | None = None,
    ):
        self.graph_queries = graph_queries or GraphQueries()
        self._init_llm_client()

    def _init_llm_client(self) -> None:
        """初始化 LLM 客户端"""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")

        base_url = os.environ.get("ANTHROPIC_API_BASE_URL")
        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self.model = os.environ.get("ANTHROPIC_MODEL") or "glm-5"
        self.max_tokens = 4096

    def analyze(
        self,
        target_entity: str,
        particles: list[IntelligenceParticle] | None = None,
        max_depth: int = 3,
    ) -> RiskReport:
        """执行风险穿透分析

        Args:
            target_entity: 目标实体名称
            particles: 相关情报微粒（可选）
            max_depth: 穿透深度

        Returns:
            风险分析报告
        """
        # 1. 执行图谱查询
        risk_paths_data = self.graph_queries.risk_penetration(
            company_name=target_entity,
            max_depth=max_depth,
        )

        # 2. 计算风险传导
        risk_paths = self._calculate_risk_paths(risk_paths_data)
        total_risk = RiskCalculator.calculate_target_risk(risk_paths)
        from src.risk.weights import get_risk_level
        risk_level = get_risk_level(total_risk)

        # 3. 生成 LLM 分析
        particles_data = [p.model_dump() for p in (particles or [])]
        analysis_result = self._generate_analysis(
            target_entity=target_entity,
            risk_paths=risk_paths_data,
            particles=particles_data,
        )

        # 4. 构建报告
        report = ReportGenerator.generate(
            target_entity=target_entity,
            risk_level=risk_level,
            risk_score=total_risk,
            conclusions=analysis_result.get("conclusions", []),
            conflicts=analysis_result.get("conflicts", []),
            risk_paths=[
                {
                    "chain": p.get("nodes", []),
                    "weighted_risk": p.get("cumulative_risk", 0),
                }
                for p in risk_paths_data
            ],
            source_particles=[p.id for p in (particles or [])],
        )

        return report

    def _calculate_risk_paths(
        self,
        risk_paths_data: list[dict],
    ) -> list[RiskPath]:
        """计算风险传导路径

        Args:
            risk_paths_data: 图谱查询结果

        Returns:
            风险路径列表
        """
        from datetime import date

        risk_paths: list[RiskPath] = []

        for path_data in risk_paths_data:
            nodes = path_data.get("nodes", [])
            edges = path_data.get("edges", [])

            if not nodes or not edges:
                continue

            # 构建关系链
            relation_chain = [e.get("type", "UNKNOWN") for e in edges]

            # 计算路径权重
            from src.risk.weights import calculate_path_weight
            from src.schemas.enums import RelationType

            relations = []
            for rel_name in relation_chain:
                try:
                    relations.append(RelationType[rel_name])
                except KeyError:
                    pass

            path_weight = calculate_path_weight(relations) if relations else 0.3

            risk_paths.append(
                RiskPath(
                    source_id=nodes[0].get("id", "unknown"),
                    source_risk=path_data.get("cumulative_risk", 0.5),
                    path_weight=path_weight,
                    time_decay=1.0,  # 默认不衰减
                    relation_chain=relation_chain,
                    event_date=date.today(),
                )
            )

        return risk_paths

    def _generate_analysis(
        self,
        target_entity: str,
        risk_paths: list[dict],
        particles: list[dict],
    ) -> dict:
        """调用 LLM 生成分析

        Args:
            target_entity: 目标实体
            risk_paths: 风险路径
            particles: 情报微粒

        Returns:
            分析结果
        """
        user_prompt = build_analysis_prompt(target_entity, risk_paths, particles)

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
            return json.loads(content) if content else {}
        except json.JSONDecodeError:
            # 如果不是有效 JSON，返回默认结构
            return {
                "conclusions": [
                    {
                        "conclusion": content,
                        "source_particle_ids": [],
                        "confidence": 0.5,
                    }
                ],
                "conflicts": [],
            }

    def query_with_cypher(
        self,
        cypher: str,
        parameters: dict | None = None,
    ) -> list[dict]:
        """执行自定义 Cypher 查询

        Args:
            cypher: Cypher 查询语句
            parameters: 查询参数

        Returns:
            查询结果
        """
        from src.graph.connection import get_connection

        with get_connection().session() as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]
