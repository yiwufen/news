"""
图谱同步模块

将 Intelligence Particle 的图谱数据同步到 Neo4j。
"""

from datetime import date

from src.graph import EdgeRepository, NodeRepository
from src.schemas import EntityType, GraphEdge, GraphNode, GraphUpdates, IntelligenceParticle, RelationType


class GraphSynchronizer:
    """图谱同步器"""

    def __init__(
        self,
        node_repo: NodeRepository | None = None,
        edge_repo: EdgeRepository | None = None,
    ):
        self.node_repo = node_repo or NodeRepository()
        self.edge_repo = edge_repo or EdgeRepository()

    def sync_particle(
        self,
        particle: IntelligenceParticle,
        valid_from: date | None = None,
    ) -> dict:
        """同步情报微粒的图谱数据到 Neo4j

        Args:
            particle: 情报微粒
            valid_from: 关系生效时间（默认使用事件时间）

        Returns:
            同步结果统计
        """
        graph_updates = particle.graph_updates
        if graph_updates.is_empty():
            return {
                "nodes_created": 0,
                "edges_created": 0,
                "errors": [],
            }

        # 使用事件时间作为 valid_from
        if valid_from is None:
            valid_from = particle.metadata.event_time

        stats = {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
        }

        # 1. 同步节点
        node_id_mapping: dict[str, str] = {}  # 原始 ID -> Neo4j ID
        for node in graph_updates.nodes:
            try:
                success = self.node_repo.create_node(
                    node_id=node.id,
                    label=node.label,
                    entity_type=node.type,
                    properties=node.properties,
                )
                if success:
                    stats["nodes_created"] += 1
                    node_id_mapping[node.id] = node.id
            except Exception as e:
                stats["errors"].append(f"节点创建失败 [{node.id}]: {str(e)}")

        # 2. 同步边
        for edge in graph_updates.edges:
            try:
                success = self.edge_repo.create_edge(
                    source_id=edge.source,
                    target_id=edge.target,
                    relation=edge.relation,
                    properties=edge.properties,
                    valid_from=valid_from,
                )
                if success:
                    stats["edges_created"] += 1
            except Exception as e:
                stats["errors"].append(
                    f"关系创建失败 [{edge.source} -> {edge.target}]: {str(e)}"
                )

        return stats

    def sync_graph_updates(
        self,
        graph_updates: GraphUpdates,
        valid_from: date | None = None,
    ) -> dict:
        """同步图谱更新数据

        Args:
            graph_updates: 图谱更新数据
            valid_from: 关系生效时间

        Returns:
            同步结果统计
        """
        if valid_from is None:
            valid_from = date.today()

        stats = {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
        }

        # 同步节点
        for node in graph_updates.nodes:
            try:
                success = self.node_repo.create_node(
                    node_id=node.id,
                    label=node.label,
                    entity_type=node.type,
                    properties=node.properties,
                )
                if success:
                    stats["nodes_created"] += 1
            except Exception as e:
                stats["errors"].append(f"节点创建失败 [{node.id}]: {str(e)}")

        # 同步边
        for edge in graph_updates.edges:
            try:
                success = self.edge_repo.create_edge(
                    source_id=edge.source,
                    target_id=edge.target,
                    relation=edge.relation,
                    properties=edge.properties,
                    valid_from=valid_from,
                )
                if success:
                    stats["edges_created"] += 1
            except Exception as e:
                stats["errors"].append(
                    f"关系创建失败 [{edge.source} -> {edge.target}]: {str(e)}"
                )

        return stats

    def sync_batch(
        self,
        particles: list[IntelligenceParticle],
    ) -> dict:
        """批量同步情报微粒

        Args:
            particles: 情报微粒列表

        Returns:
            批量同步统计
        """
        total_stats = {
            "particles_processed": 0,
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
        }

        for particle in particles:
            stats = self.sync_particle(particle)
            total_stats["particles_processed"] += 1
            total_stats["nodes_created"] += stats["nodes_created"]
            total_stats["edges_created"] += stats["edges_created"]
            total_stats["errors"].extend(stats["errors"])

        return total_stats
