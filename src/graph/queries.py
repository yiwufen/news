"""
Neo4j 查询模板

风险穿透查询、担保链路检测等 Cypher 查询。
按 .claude/rules/03-risk-logic.md 定义。
"""

from typing import Any

from src.graph.connection import Neo4jConnection, get_connection


class GraphQueries:
    """图谱查询类"""

    # 查询配置
    MAX_DEPTH = 3  # 默认穿透深度
    MAX_PATHS = 50  # 最大返回路径数

    def __init__(self, connection: Neo4jConnection | None = None):
        self.connection = connection or get_connection()

    def risk_penetration(
        self,
        company_name: str,
        max_depth: int = 3,
        max_paths: int = 50,
    ) -> list[dict[str, Any]]:
        """风险穿透查询 - 从目标公司向下搜索 N 层关系

        Args:
            company_name: 目标公司名称
            max_depth: 穿透深度 (默认 3 层)
            max_paths: 最大返回路径数

        Returns:
            风险路径列表
        """
        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH path = (target:Company {{name: $company_name}})-[*1..{max_depth}]-(related)
                WHERE related:Company OR related:RiskEvent
                RETURN
                    [n IN nodes(path) | {{id: n.id, name: n.name, labels: labels(n)}}] as nodes,
                    [r IN relationships(path) | {{type: type(r), properties: properties(r)}}] as edges,
                    reduce(risk = 0, n IN nodes(path) | risk + coalesce(n.risk_score, 0)) as cumulative_risk
                ORDER BY cumulative_risk DESC
                LIMIT $max_paths
                """,
                company_name=company_name,
                max_paths=max_paths,
            )
            return [
                {
                    "nodes": record["nodes"],
                    "edges": record["edges"],
                    "cumulative_risk": record["cumulative_risk"],
                }
                for record in result
            ]

    def detect_circular_guarantee(self) -> list[dict[str, Any]]:
        """检测环形担保 (A → B → A)

        风险等级: CRITICAL
        """
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (a:Company)-[:GUARANTEES]->(b:Company)-[:GUARANTEES]->(a)
                RETURN DISTINCT a.name as company_a, a.id as id_a,
                               b.name as company_b, b.id as id_b
                """
            )
            return [
                {
                    "pattern": "CIRCULAR_GUARANTEE",
                    "risk_level": "CRITICAL",
                    "companies": [
                        {"id": record["id_a"], "name": record["company_a"]},
                        {"id": record["id_b"], "name": record["company_b"]},
                    ],
                }
                for record in result
            ]

    def detect_chain_guarantee(self, min_chain_length: int = 3) -> list[dict[str, Any]]:
        """检测链式担保 (A → B → C → ...)

        风险等级: HIGH
        """
        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH path = (start:Company)-[:GUARANTEES*{min_chain_length}..5]->(end:Company)
                WHERE start <> end
                RETURN
                    [n IN nodes(path) | {{id: n.id, name: n.name}}] as chain,
                    length(path) as chain_length
                ORDER BY chain_length DESC
                LIMIT 20
                """
            )
            return [
                {
                    "pattern": "CHAIN_GUARANTEE",
                    "risk_level": "HIGH",
                    "chain": record["chain"],
                    "chain_length": record["chain_length"],
                }
                for record in result
            ]

    def detect_many_to_one_guarantee(self) -> list[dict[str, Any]]:
        """检测多对一担保 (A → C, B → C, ...)

        风险等级: MEDIUM
        """
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (guarantor:Company)-[:GUARANTEES]->(target:Company)
                WITH target, collect(guarantor) as guarantors, count(guarantor) as guarantor_count
                WHERE guarantor_count >= 2
                RETURN
                    target.id as target_id,
                    target.name as target_name,
                    [g IN guarantors | {{id: g.id, name: g.name}}] as guarantors,
                    guarantor_count
                ORDER BY guarantor_count DESC
                """
            )
            return [
                {
                    "pattern": "MANY_TO_ONE_GUARANTEE",
                    "risk_level": "MEDIUM",
                    "target": {
                        "id": record["target_id"],
                        "name": record["target_name"],
                    },
                    "guarantors": record["guarantors"],
                    "guarantor_count": record["guarantor_count"],
                }
                for record in result
            ]

    def get_company_network(
        self,
        company_name: str,
        depth: int = 2,
    ) -> dict[str, Any]:
        """获取公司关系网络（用于可视化）

        Args:
            company_name: 公司名称
            depth: 关系深度 (1-3)

        Returns:
            包含 nodes 和 edges 的网络数据
        """
        with self.connection.session() as session:
            result = session.run(
                f"""
                MATCH path = (center:Company {{name: $company_name}})-[*1..{depth}]-(related)
                WITH collect(DISTINCT related) + center as all_nodes, collect(path) as all_paths
                UNWIND all_nodes as node
                WITH all_nodes, all_paths, node
                OPTIONAL MATCH (node)-[r]-(connected)
                WHERE connected IN all_nodes
                WITH all_nodes, collect(DISTINCT r) as all_edges
                RETURN
                    [n IN all_nodes | {{id: n.id, name: n.name, labels: labels(n)}}] as nodes,
                    [e IN all_edges | {{source: startNode(e).id, target: endNode(e).id, type: type(e), properties: properties(e)}}] as edges
                """,
                company_name=company_name,
            )
            record = result.single()
            if record:
                return {
                    "nodes": record["nodes"],
                    "edges": record["edges"],
                }
            return {"nodes": [], "edges": []}

    def calculate_total_guarantee_amount(
        self,
        company_name: str,
    ) -> dict[str, Any]:
        """计算公司的总担保金额"""
        with self.connection.session() as session:
            result = session.run(
                """
                MATCH (c:Company {name: $company_name})

                // 作为担保人的担保金额
                OPTIONAL MATCH (c)-[out:GUARANTEES]->(target)
                WITH c, sum(out.amount) as outgoing_guarantee

                // 被担保的金额
                OPTIONAL MATCH (guarantor)-[in:GUARANTEES]->(c)
                WITH c, outgoing_guarantee, sum(in.amount) as incoming_guarantee

                RETURN
                    c.id as company_id,
                    c.name as company_name,
                    coalesce(outgoing_guarantee, 0) as outgoing_guarantee,
                    coalesce(incoming_guarantee, 0) as incoming_guarantee
                """,
                company_name=company_name,
            )
            record = result.single()
            if record:
                return {
                    "company_id": record["company_id"],
                    "company_name": record["company_name"],
                    "outgoing_guarantee": record["outgoing_guarantee"],
                    "incoming_guarantee": record["incoming_guarantee"],
                    "net_guarantee": record["outgoing_guarantee"] - record["incoming_guarantee"],
                }
            return {}
