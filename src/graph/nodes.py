"""
Neo4j 节点 Repository

节点的创建、查询、更新操作。
"""

from typing import Any

from src.graph.connection import Neo4jConnection, get_connection
from src.schemas.enums import EntityType


class NodeRepository:
    """节点 Repository"""

    # 实体类型到 Neo4j 标签的映射
    ENTITY_TYPE_LABELS: dict[EntityType, str] = {
        EntityType.COMPANY: "Company",
        EntityType.PERSON: "Person",
        EntityType.ASSET: "Asset",
        EntityType.FINANCIAL_PRODUCT: "FinancialProduct",
    }

    def __init__(self, connection: Neo4jConnection | None = None):
        self.connection = connection or get_connection()

    def create_node(
        self,
        node_id: str,
        label: str,
        entity_type: EntityType,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """创建节点

        Args:
            node_id: 节点唯一标识
            label: 显示名称
            entity_type: 实体类型
            properties: 扩展属性

        Returns:
            是否创建成功
        """
        neo4j_label = self.ENTITY_TYPE_LABELS.get(entity_type, "Entity")
        props = properties or {}
        props["id"] = node_id
        props["name"] = label

        with self.connection.session() as session:
            result = session.run(
                f"""
                MERGE (n:{neo4j_label} {{id: $node_id}})
                SET n += $props
                RETURN n.id as id
                """,
                node_id=node_id,
                props=props,
            )
            return result.single() is not None

    def get_node_by_id(self, node_id: str) -> dict[str, Any] | None:
        """根据 ID 获取节点"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (n {id: $node_id})
                RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties
                """,
                node_id=node_id,
            )
            record = result.single()
            if record:
                return {
                    "id": record["id"],
                    "name": record["name"],
                    "labels": record["labels"],
                    "properties": record["properties"],
                }
            return None

    def find_node_by_name(self, name: str) -> dict[str, Any] | None:
        """根据名称查找节点"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (n {name: $name})
                RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties
                """,
                name=name,
            )
            record = result.single()
            if record:
                return {
                    "id": record["id"],
                    "name": record["name"],
                    "labels": record["labels"],
                    "properties": record["properties"],
                }
            return None

    def find_nodes_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        """根据名称列表批量查找节点

        Args:
            names: 名称列表

        Returns:
            匹配的节点列表
        """
        if not names:
            return []

        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (n)
                WHERE n.name IN $names
                RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties
                """,
                names=names,
            )
            return [
                {
                    "id": record["id"],
                    "name": record["name"],
                    "labels": record["labels"],
                    "properties": record["properties"],
                }
                for record in result
            ]

    def find_nodes_by_type(self, entity_type: EntityType, limit: int = 100) -> list[dict[str, Any]]:
        """根据类型获取节点列表"""
        neo4j_label = self.ENTITY_TYPE_LABELS.get(entity_type, "Entity")

        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH (n:{neo4j_label})
                RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties
                LIMIT $limit
                """,
                limit=limit,
            )
            return [
                {
                    "id": record["id"],
                    "name": record["name"],
                    "labels": record["labels"],
                    "properties": record["properties"],
                }
                for record in result
            ]

    def update_node_properties(
        self,
        node_id: str,
        properties: dict[str, Any],
    ) -> bool:
        """更新节点属性"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (n {id: $node_id})
                SET n += $properties
                RETURN n.id as id
                """,
                node_id=node_id,
                properties=properties,
            )
            return result.single() is not None

    def delete_node(self, node_id: str) -> bool:
        """删除节点及其所有关系"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (n {id: $node_id})
                DETACH DELETE n
                RETURN count(n) as deleted
                """,
                node_id=node_id,
            )
            record = result.single()
            return record is not None and record["deleted"] > 0
