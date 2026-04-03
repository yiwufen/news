"""
图谱数据模型

定义节点和边的数据结构，用于构建"公司-债务-担保"关系图谱。
"""

from typing import Any

from pydantic import BaseModel, Field

from src.schemas.enums import EntityType, RelationType


class GraphNode(BaseModel):
    """
    图谱节点

    代表图谱中的一个实体（公司、人物、资产等）。
    """

    id: str = Field(
        ...,
        description="节点唯一标识（建议使用统一社会信用代码或标准化名称）",
    )
    label: str = Field(
        ...,
        description="节点显示名称（公司全称/人名/资产名称）",
    )
    type: EntityType = Field(
        ...,
        description="实体类型",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展属性（如工商号、注册地址等）",
    )


class GraphEdge(BaseModel):
    """
    图谱边

    代表两个实体之间的关系（投资、担保、控制等）。
    """

    source: str = Field(
        ...,
        description="源节点 ID",
    )
    target: str = Field(
        ...,
        description="目标节点 ID",
    )
    relation: RelationType = Field(
        ...,
        description="关系类型",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="关系属性（金额、比例、时间等）",
    )

    def get_amount(self) -> float | None:
        """获取金额（万元）"""
        return self.properties.get("amount")

    def get_percent(self) -> float | None:
        """获取比例（0-1）"""
        return self.properties.get("percent")


class GraphUpdates(BaseModel):
    """
    图谱更新数据

    Worker Agent 提取的结构化图谱数据，用于 Integrator Agent 写入 Neo4j。
    """

    nodes: list[GraphNode] = Field(
        default_factory=list,
        description="节点列表",
    )
    edges: list[GraphEdge] = Field(
        default_factory=list,
        description="边列表",
    )

    def is_empty(self) -> bool:
        """检查是否有有效数据"""
        return len(self.nodes) == 0 and len(self.edges) == 0
