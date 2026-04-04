"""
Integrator Agent - 实体对齐与图谱同步

按 .claude/rules/02-prompts.md 定义的 Integrator Agent 规范。
支持可选的图谱同步。
"""

from datetime import date

from src.agents.integrator.alignment import EntityAlignment, find_best_match
from src.agents.integrator.sync import GraphSynchronizer
from src.graph import NodeRepository
from src.schemas import EntityType, IntelligenceParticle


class IntegratorAgent:
    """Integrator Agent

    职责：
    1. 实体对齐：查询数据库中是否存在同名/相似公司
    2. ID 合并：若存在则使用现有 ID，若不存在则创建新 ID
    3. 图谱写入：将 nodes 和 edges 写入 Neo4j（可选）
    """

    def __init__(
        self,
        node_repo: NodeRepository | None = None,
        threshold: float = 0.9,
        graph_enabled: bool = True,
    ):
        """初始化 Integrator Agent

        Args:
            node_repo: 节点仓库（可选）
            threshold: 实体对齐相似度阈值
            graph_enabled: 是否启用图谱同步
        """
        self.graph_enabled = graph_enabled
        self.alignment = EntityAlignment(threshold=threshold)

        # 图谱相关组件仅在启用时初始化
        if graph_enabled:
            self.node_repo = node_repo or NodeRepository()
            self.synchronizer = GraphSynchronizer()
        else:
            self.node_repo = None
            self.synchronizer = None

    def process_particle(
        self,
        particle: IntelligenceParticle,
    ) -> dict:
        """处理单个情报微粒

        流程：
        1. 实体对齐（始终执行）
        2. 图谱同步（可选）

        Args:
            particle: 情报微粒

        Returns:
            处理结果
        """
        result = {
            "particle_id": particle.id,
            "entity_alignment": [],
            "sync_result": None,
        }

        # 1. 实体对齐
        graph_updates = particle.graph_updates

        # 获取现有实体（仅图谱启用时）
        existing_entities = []
        if self.graph_enabled and self.node_repo:
            existing_entities = self._get_existing_entities(graph_updates.nodes)

        for node in graph_updates.nodes:
            # 跳过非公司实体（暂不对齐 Person/Asset）
            if node.type != EntityType.COMPANY:
                result["entity_alignment"].append({
                    "original_id": node.id,
                    "action": "create",
                    "reason": f"非公司实体类型: {node.type.value}",
                })
                continue

            # 执行对齐
            alignment_result = self.alignment.align(
                entity_name=node.label,
                entity_type=node.type.value,
                credit_code=node.properties.get("credit_code"),
                existing_entities=existing_entities,
            )

            result["entity_alignment"].append({
                "original_id": node.id,
                "action": alignment_result["action"],
                "matched_id": alignment_result["matched_id"],
                "similarity": alignment_result["similarity"],
                "reason": alignment_result["reason"],
            })

            # 如果需要合并，更新边的 source/target
            if alignment_result["action"] == "merge" and alignment_result["matched_id"]:
                self._update_edge_references(
                    graph_updates,
                    node.id,
                    alignment_result["matched_id"],
                )

        # 2. 图谱同步（仅在启用时执行）
        if self.graph_enabled and self.synchronizer:
            result["sync_result"] = self.synchronizer.sync_particle(particle)
        else:
            # 无图谱模式：返回模拟结果
            result["sync_result"] = {
                "nodes_created": len(graph_updates.nodes),
                "edges_created": len(graph_updates.edges),
                "errors": [],
                "skipped": True,
                "reason": "图谱同步已禁用",
            }

        return result

    def _get_existing_entities(self, nodes: list) -> list[dict]:
        """获取现有实体列表

        Args:
            nodes: 新提取的节点列表

        Returns:
            现有实体列表 [{"name": "xxx", "id": "xxx", "credit_code": "xxx"}, ...]
        """
        if not self.node_repo:
            return []

        # 提取所有需要查询的名称（仅查询公司类型）
        company_names = [
            node.label for node in nodes
            if node.type == EntityType.COMPANY
        ]

        if not company_names:
            return []

        # 批量查询同名实体
        try:
            found_nodes = self.node_repo.find_nodes_by_names(company_names)
        except Exception:
            # 图谱不可用时返回空列表
            return []

        return [
            {
                "id": node["id"],
                "name": node["name"],
                "credit_code": node["properties"].get("credit_code"),
            }
            for node in found_nodes
        ]

    def _update_edge_references(
        self,
        graph_updates,
        old_id: str,
        new_id: str,
    ) -> None:
        """更新边引用（合并实体时）

        Args:
            graph_updates: 图谱更新数据
            old_id: 原 ID
            new_id: 新 ID
        """
        for edge in graph_updates.edges:
            if edge.source == old_id:
                edge.source = new_id
            if edge.target == old_id:
                edge.target = new_id

    def process_batch(
        self,
        particles: list[IntelligenceParticle],
    ) -> list[dict]:
        """批量处理情报微粒

        Args:
            particles: 情报微粒列表

        Returns:
            处理结果列表
        """
        return [self.process_particle(p) for p in particles]

    def run(
        self,
        particles: list[IntelligenceParticle],
    ) -> dict:
        """运行 Integrator Agent

        Args:
            particles: 情报微粒列表

        Returns:
            运行统计和详细结果
        """
        results = self.process_batch(particles)

        stats = {
            "particles_processed": len(particles),
            "entities_created": 0,
            "entities_merged": 0,
            "entities_suspected": 0,
            "edges_created": 0,
            "errors": [],
            "details": results,  # 包含详细结果，避免重复调用
            "graph_enabled": self.graph_enabled,
        }

        for result in results:
            for alignment in result["entity_alignment"]:
                action = alignment["action"]
                if action == "create":
                    stats["entities_created"] += 1
                elif action == "merge":
                    stats["entities_merged"] += 1
                elif action == "suspected":
                    stats["entities_suspected"] += 1

            if result["sync_result"]:
                stats["edges_created"] += result["sync_result"].get("edges_created", 0)
                stats["errors"].extend(result["sync_result"].get("errors", []))

        return stats
