"""
Master Agent - 风险穿透分析

按 .claude/rules/02-prompts.md 定义的 Master Agent 规范。
支持可选的图谱依赖。
"""

from datetime import date

from src.agents.master.prompts import SYSTEM_PROMPT, build_analysis_prompt
from src.agents.master.report import ReportGenerator, RiskReport
from src.graph import GraphQueries
from src.llm import create_llm_client, extract_text_from_response, parse_json_from_text, DEFAULT_MAX_TOKENS
from src.risk import RiskCalculator, RiskPath
from src.risk.weights import calculate_path_weight, get_risk_level
from src.schemas import IntelligenceParticle
from src.schemas.enums import RelationType, RiskLevel


class MasterAgent:
    """Master Agent

    职责：
    1. 接收分析师查询
    2. 执行 Cypher 查询，向下搜索 3 层关系路径（可选）
    3. 计算风险传导分值
    4. 生成带溯源的分析报告
    5. 生成实体时间线（无图谱模式）
    """

    def __init__(
        self,
        graph_queries: GraphQueries | None = None,
        graph_enabled: bool = True,
    ):
        """初始化 Master Agent

        Args:
            graph_queries: 图谱查询器（可选）
            graph_enabled: 是否启用图谱查询
        """
        self.graph_enabled = graph_enabled

        if graph_enabled:
            self.graph_queries = graph_queries or GraphQueries()
        else:
            self.graph_queries = None

        self.client, self.model = create_llm_client()
        self.max_tokens = DEFAULT_MAX_TOKENS

    def generate_timeline(
        self,
        entity: str,
        particles: list[IntelligenceParticle],
    ) -> dict:
        """生成实体时间线

        不依赖图谱，仅基于情报微粒生成时间线。

        Args:
            entity: 目标实体
            particles: 相关情报微粒

        Returns:
            时间线数据
        """
        # 标准化 particles
        particles = particles or []

        # 按时间排序情报微粒
        sorted_particles = sorted(
            particles,
            key=lambda p: p.event_time,
            reverse=True,
        )

        # 提取与实体相关的事件
        timeline_events = []
        for p in sorted_particles:
            if self._particle_mentions_entity(p, entity):
                timeline_events.append({
                    "date": p.event_time.isoformat(),
                    "event_type": p.event_type.value,
                    "description": p.risk_signal.description,
                    "risk_level": p.risk_level.value,
                    "source_ids": p.source_doc_ids,
                    "particle_id": p.id,
                })

        return {
            "entity": entity,
            "events": timeline_events,
            "total_events": len(timeline_events),
            "time_range": {
                "start": timeline_events[-1]["date"] if timeline_events else None,
                "end": timeline_events[0]["date"] if timeline_events else None,
            },
        }

    def _particle_mentions_entity(
        self,
        particle: IntelligenceParticle,
        entity: str,
    ) -> bool:
        """检查情报微粒是否提及实体

        Args:
            particle: 情报微粒
            entity: 实体名称

        Returns:
            是否提及
        """
        entity_lower = entity.lower()

        # 检查图谱节点
        for node in particle.graph_updates.nodes:
            if entity_lower in node.label.lower():
                return True

        # 检查描述
        if entity_lower in particle.risk_signal.description.lower():
            return True

        return False

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
        particles = particles or []

        if self.graph_enabled and self.graph_queries:
            try:
                risk_paths_data = self.graph_queries.risk_penetration(
                    company_name=target_entity,
                    max_depth=max_depth,
                )
            except Exception:
                risk_paths_data = self._build_paths_from_particles(target_entity, particles)
        else:
            risk_paths_data = self._build_paths_from_particles(target_entity, particles)

        risk_paths = self._calculate_risk_paths(risk_paths_data)
        total_risk = RiskCalculator.calculate_target_risk(risk_paths)
        risk_level = get_risk_level(total_risk)

        particles_data = [p.model_dump() for p in particles]
        analysis_result = self._generate_analysis(
            target_entity=target_entity,
            risk_paths=risk_paths_data,
            particles=particles_data,
        )

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
            source_particles=[p.id for p in particles],
        )

        return report

    def _build_paths_from_particles(
        self,
        entity: str,
        particles: list[IntelligenceParticle],
    ) -> list[dict]:
        """从情报微粒构建风险路径（无图谱模式）

        Args:
            entity: 目标实体
            particles: 情报微粒列表

        Returns:
            风险路径列表
        """
        paths = []

        for p in particles:
            if self._particle_mentions_entity(p, entity):
                # 根据风险等级确定分值
                high_risk_levels = {RiskLevel.HIGH, RiskLevel.CRITICAL}
                risk_score = 0.7 if p.risk_level in high_risk_levels else 0.4

                paths.append({
                    "nodes": [{"id": n.id, "name": n.label} for n in p.graph_updates.nodes],
                    "edges": [{"type": e.relation.value} for e in p.graph_updates.edges],
                    "cumulative_risk": risk_score,
                    "source_particle": p.id,
                })

        return paths

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
        risk_paths: list[RiskPath] = []

        for path_data in risk_paths_data:
            nodes = path_data.get("nodes", [])
            edges = path_data.get("edges", [])

            if not nodes:
                continue

            # 构建关系链
            relation_chain = [e.get("type", "UNKNOWN") for e in edges]

            # 计算路径权重
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
        content = extract_text_from_response(response)
        return parse_json_from_text(content, default={
            "conclusions": [{"conclusion": content, "source_particle_ids": [], "confidence": 0.5}],
            "conflicts": [],
        })

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
        if not self.graph_enabled or not self.graph_queries:
            raise RuntimeError("图谱功能已禁用，无法执行 Cypher 查询")

        from src.graph.connection import get_connection

        with get_connection().session() as session:
            result = session.run(cypher, parameters or {})
            return [dict(record) for record in result]
