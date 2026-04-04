"""
Neo4j 边 Repository

关系的创建、查询操作。
"""

from datetime import date
from typing import Any

from src.graph.connection import Neo4jConnection, get_connection
from src.schemas.enums import RelationType


class EdgeRepository:
    """边 Repository"""

    # 关系类型到 Neo4j 关系名称的映射
    RELATION_TYPE_NAMES: dict[RelationType, str] = {
        RelationType.INVESTS: "INVESTS",
        RelationType.GUARANTEES: "GUARANTEES",
        RelationType.DEBTOR_OF: "DEBTOR_OF",
        RelationType.ACTUAL_CONTROL: "ACTUAL_CONTROL",
        RelationType.OWNS: "OWNS",
        RelationType.ISSUES: "ISSUES",
    }

    def __init__(self, connection: Neo4jConnection | None = None):
        self.connection = connection or get_connection()

    def create_edge(
        self,
        source_id: str,
        target_id: str,
        relation: RelationType,
        properties: dict[str, Any] | None = None,
        valid_from: date | None = None,
    ) -> bool:
        """创建关系（使用 MERGE 避免重复）

        Args:
            source_id: 源节点 ID
            target_id: 目标节点 ID
            relation: 关系类型
            properties: 关系属性（amount, percent 等）
            valid_from: 关系生效时间

        Returns:
            是否创建成功
        """
        rel_name = self.RELATION_TYPE_NAMES.get(relation, "RELATED_TO")
        props = properties or {}

        # 添加 valid_from 时间戳
        if valid_from:
            props["valid_from"] = valid_from.isoformat()
        else:
            props["valid_from"] = date.today().isoformat()

        with self.connection.session() as session:
            # 使用 MERGE 避免重复创建相同的关系
            # 基于 source, target, relation type 和 valid_from 进行去重
            result = session.run(
                f"""
                MATCH (source {{id: $source_id}})
                MATCH (target {{id: $target_id}})
                MERGE (source)-[r:{rel_name} {{valid_from: $valid_from}}]->(target)
                SET r += $props
                RETURN type(r) as relation_type
                """,
                source_id=source_id,
                target_id=target_id,
                valid_from=props["valid_from"],
                props=props,
            )
            return result.single() is not None

    def get_edges_between(
        self,
        source_id: str,
        target_id: str,
    ) -> list[dict[str, Any]]:
        """获取两个节点之间的所有关系"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (source {id: $source_id})-[r]->(target {id: $target_id})
                RETURN type(r) as relation_type, properties(r) as properties
                """,
                source_id=source_id,
                target_id=target_id,
            )
            return [
                {
                    "relation_type": record["relation_type"],
                    "properties": record["properties"],
                }
                for record in result
            ]

    def get_outgoing_edges(
        self,
        node_id: str,
        relation: RelationType | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取节点的出边"""
        rel_filter = ""
        if relation:
            rel_name = self.RELATION_TYPE_NAMES.get(relation, "RELATED_TO")
            rel_filter = f":{rel_name}"

        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH (n {{id: $node_id}})-[r{rel_filter}]->(target)
                RETURN type(r) as relation_type, target.id as target_id, properties(r) as properties
                LIMIT $limit
                """,
                node_id=node_id,
                limit=limit,
            )
            return [
                {
                    "relation_type": record["relation_type"],
                    "target_id": record["target_id"],
                    "properties": record["properties"],
                }
                for record in result
            ]

    def get_incoming_edges(
        self,
        node_id: str,
        relation: RelationType | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取节点的入边"""
        rel_filter = ""
        if relation:
            rel_name = self.RELATION_TYPE_NAMES.get(relation, "RELATED_TO")
            rel_filter = f":{rel_name}"

        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH (source)-[r{rel_filter}]->(n {{id: $node_id}})
                RETURN type(r) as relation_type, source.id as source_id, properties(r) as properties
                LIMIT $limit
                """,
                node_id=node_id,
                limit=limit,
            )
            return [
                {
                    "relation_type": record["relation_type"],
                    "source_id": record["source_id"],
                    "properties": record["properties"],
                }
                for record in result
            ]

    def delete_edges_between(
        self,
        source_id: str,
        target_id: str,
        relation: RelationType | None = None,
    ) -> int:
        """删除两个节点之间的关系"""
        rel_filter = ""
        if relation:
            rel_name = self.RELATION_TYPE_NAMES.get(relation, "RELATED_TO")
            rel_filter = f":{rel_name}"

        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH (source {{id: $source_id}})-[r{rel_filter}]->(target {{id: $target_id}})
                DELETE r
                RETURN count(r) as deleted
                """,
                source_id=source_id,
                target_id=target_id,
            )
            record = result.single()
            return record["deleted"] if record else 0
