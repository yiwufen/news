"""
Neo4j Schema 初始化

创建索引和约束。
"""

from src.graph.connection import Neo4jConnection, get_connection


class GraphSchema:
    """图谱 Schema 管理类"""

    def __init__(self, connection: Neo4jConnection | None = None):
        self.connection = connection or get_connection()

    def initialize(self) -> None:
        """初始化图数据库 Schema

        创建节点标签、索引和约束。
        """
        with self.connection.session() as session:
            # === 节点约束 ===

            # Company 节点
            session.run(
                """
                CREATE CONSTRAINT company_id_unique IF NOT EXISTS
                FOR (c:Company) REQUIRE c.id IS UNIQUE
                """
            )
            session.run(
                """
                CREATE INDEX company_name_index IF NOT EXISTS
                FOR (c:Company) ON (c.name)
                """
            )

            # Person 节点
            session.run(
                """
                CREATE CONSTRAINT person_id_unique IF NOT EXISTS
                FOR (p:Person) REQUIRE p.id IS UNIQUE
                """
            )

            # Asset 节点
            session.run(
                """
                CREATE CONSTRAINT asset_id_unique IF NOT EXISTS
                FOR (a:Asset) REQUIRE a.id IS UNIQUE
                """
            )

            # FinancialProduct 节点
            session.run(
                """
                CREATE CONSTRAINT financial_product_id_unique IF NOT EXISTS
                FOR (f:FinancialProduct) REQUIRE f.id IS UNIQUE
                """
            )

            # RiskEvent 节点
            session.run(
                """
                CREATE CONSTRAINT risk_event_id_unique IF NOT EXISTS
                FOR (r:RiskEvent) REQUIRE r.id IS UNIQUE
                """
            )

            # === 关系索引 ===

            # GUARANTEES 关系的时间索引
            session.run(
                """
                CREATE INDEX guarantee_valid_from_index IF NOT EXISTS
                FOR ()-[r:GUARANTEES]-() ON (r.valid_from)
                """
            )

            # INVESTS 关系的时间索引
            session.run(
                """
                CREATE INDEX invests_valid_from_index IF NOT EXISTS
                FOR ()-[r:INVESTS]-() ON (r.valid_from)
                """
            )

    def drop_all(self) -> None:
        """删除所有约束和索引（危险操作，仅用于测试）"""
        with self.connection.session() as session:
            # 删除约束
            constraints = session.run("SHOW CONSTRAINTS")
            for record in constraints:
                session.run(f"DROP CONSTRAINT {record['name']}")

            # 删除索引
            indexes = session.run("SHOW INDEXES")
            for record in indexes:
                if not record["owningConstraint"]:  # 仅删除非约束索引
                    session.run(f"DROP INDEX {record['name']}")

    def get_schema_info(self) -> dict[str, list[dict]]:
        """获取当前 Schema 信息"""
        with self.connection.session() as session:
            constraints = list(session.run("SHOW CONSTRAINTS"))
            indexes = list(session.run("SHOW INDEXES"))

            return {
                "constraints": [
                    {
                        "name": r["name"],
                        "type": r["type"],
                        "labelsOrTypes": r["labelsOrTypes"],
                    }
                    for r in constraints
                ],
                "indexes": [
                    {
                        "name": r["name"],
                        "labelsOrTypes": r["labelsOrTypes"],
                        "properties": r["properties"],
                    }
                    for r in indexes
                ],
            }
