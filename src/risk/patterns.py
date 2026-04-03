"""
特殊风险模式检测

按 .claude/rules/03-risk-logic.md 定义的特殊风险模式。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PatternType(Enum):
    """风险模式类型"""

    CIRCULAR_GUARANTEE = "环形担保"
    CHAIN_GUARANTEE = "链式担保"
    MANY_TO_ONE_GUARANTEE = "多对一担保"


class PatternRiskLevel(Enum):
    """模式风险等级"""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


@dataclass
class RiskPattern:
    """检测到的风险模式"""

    pattern_type: PatternType
    risk_level: PatternRiskLevel
    entities: list[dict[str, Any]]  # 涉及实体
    description: str
    properties: dict[str, Any]  # 扩展属性


class PatternDetector:
    """风险模式检测器"""

    @classmethod
    def detect_circular_guarantee(
        cls,
        guarantee_edges: list[dict[str, Any]],
    ) -> list[RiskPattern]:
        """检测环形担保 (A → B → A)

        风险等级: CRITICAL
        处理: 自动标记，触发人工审核

        Args:
            guarantee_edges: 担保关系边列表
                [{"source": "A", "target": "B"}, ...]

        Returns:
            检测到的环形担保模式
        """
        patterns: list[RiskPattern] = []

        # 构建邻接表
        adjacency: dict[str, set[str]] = {}
        for edge in guarantee_edges:
            source = edge["source"]
            target = edge["target"]
            if source not in adjacency:
                adjacency[source] = set()
            adjacency[source].add(target)

        # 检测双向担保
        checked: set[tuple[str, str]] = set()
        for source, targets in adjacency.items():
            for target in targets:
                if (source, target) in checked or (target, source) in checked:
                    continue

                # 检查是否存在反向担保
                if target in adjacency and source in adjacency[target]:
                    patterns.append(
                        RiskPattern(
                            pattern_type=PatternType.CIRCULAR_GUARANTEE,
                            risk_level=PatternRiskLevel.CRITICAL,
                            entities=[
                                {"id": source, "role": "担保方A"},
                                {"id": target, "role": "担保方B"},
                            ],
                            description=f"检测到环形担保：{source} 与 {target} 互相担保",
                            properties={
                                "bilateral": True,
                            },
                        )
                    )
                    checked.add((source, target))
                    checked.add((target, source))

        return patterns

    @classmethod
    def detect_chain_guarantee(
        cls,
        guarantee_edges: list[dict[str, Any]],
        min_chain_length: int = 3,
    ) -> list[RiskPattern]:
        """检测链式担保 (A → B → C → ...)

        风险等级: HIGH
        处理: 计算累积风险分值

        Args:
            guarantee_edges: 担保关系边列表
            min_chain_length: 最小链长度

        Returns:
            检测到的链式担保模式
        """
        patterns: list[RiskPattern] = []

        # 构建邻接表
        adjacency: dict[str, list[str]] = {}
        for edge in guarantee_edges:
            source = edge["source"]
            target = edge["target"]
            if source not in adjacency:
                adjacency[source] = []
            adjacency[source].append(target)

        # DFS 搜索链路
        def find_chains(
            start: str,
            current_chain: list[str],
            visited: set[str],
        ) -> list[list[str]]:
            chains: list[list[str]] = []
            if len(current_chain) >= min_chain_length:
                chains.append(current_chain.copy())

            if start not in adjacency:
                return chains

            for next_node in adjacency[start]:
                if next_node not in visited:
                    visited.add(next_node)
                    current_chain.append(next_node)
                    chains.extend(find_chains(next_node, current_chain, visited))
                    current_chain.pop()
                    visited.remove(next_node)

            return chains

        # 从每个节点开始搜索
        all_chains: list[list[str]] = []
        visited_starts: set[str] = set()

        for start in adjacency:
            if start not in visited_starts:
                visited_starts.add(start)
                chains = find_chains(start, [start], {start})
                all_chains.extend(chains)

        # 去重并生成模式
        unique_chains: set[tuple[str, ...]] = set()
        for chain in all_chains:
            chain_tuple = tuple(chain)
            if chain_tuple not in unique_chains:
                unique_chains.add(chain_tuple)
                patterns.append(
                    RiskPattern(
                        pattern_type=PatternType.CHAIN_GUARANTEE,
                        risk_level=PatternRiskLevel.HIGH,
                        entities=[
                            {"id": entity, "position": i}
                            for i, entity in enumerate(chain)
                        ],
                        description=f"检测到链式担保：{' → '.join(chain)}",
                        properties={
                            "chain_length": len(chain),
                        },
                    )
                )

        return patterns

    @classmethod
    def detect_many_to_one_guarantee(
        cls,
        guarantee_edges: list[dict[str, Any]],
        min_guarantors: int = 2,
    ) -> list[RiskPattern]:
        """检测多对一担保 (A → C, B → C, ...)

        风险等级: MEDIUM
        处理: 聚合计算总担保金额

        Args:
            guarantee_edges: 担保关系边列表
            min_guarantors: 最小担保方数量

        Returns:
            检测到的多对一担保模式
        """
        patterns: list[RiskPattern] = []

        # 统计每个目标被担保的次数
        target_guarantors: dict[str, list[dict[str, Any]]] = {}
        for edge in guarantee_edges:
            target = edge["target"]
            source = edge["source"]
            if target not in target_guarantors:
                target_guarantors[target] = []
            target_guarantors[target].append({
                "id": source,
                "amount": edge.get("properties", {}).get("amount", 0),
            })

        # 检测多对一模式
        for target, guarantors in target_guarantors.items():
            if len(guarantors) >= min_guarantors:
                total_amount = sum(g.get("amount", 0) for g in guarantors)
                patterns.append(
                    RiskPattern(
                        pattern_type=PatternType.MANY_TO_ONE_GUARANTEE,
                        risk_level=PatternRiskLevel.MEDIUM,
                        entities=[
                            {"id": target, "role": "被担保方"},
                        ] + [{"id": g["id"], "role": "担保方"} for g in guarantors],
                        description=f"检测到多对一担保：{len(guarantors)} 方担保 {target}",
                        properties={
                            "guarantor_count": len(guarantors),
                            "total_amount": total_amount,
                        },
                    )
                )

        return patterns

    @classmethod
    def detect_all_patterns(
        cls,
        guarantee_edges: list[dict[str, Any]],
    ) -> list[RiskPattern]:
        """检测所有风险模式

        Args:
            guarantee_edges: 担保关系边列表

        Returns:
            所有检测到的风险模式
        """
        patterns: list[RiskPattern] = []

        # 按风险等级从高到低检测
        patterns.extend(cls.detect_circular_guarantee(guarantee_edges))
        patterns.extend(cls.detect_chain_guarantee(guarantee_edges))
        patterns.extend(cls.detect_many_to_one_guarantee(guarantee_edges))

        return patterns
