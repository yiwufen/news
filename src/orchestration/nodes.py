"""
LangGraph 节点函数

定义各个 Agent 节点的处理逻辑。
"""

from typing import Any

from src.agents.critic import CriticAgent
from src.agents.integrator import IntegratorAgent
from src.agents.master import MasterAgent
from src.agents.worker import WorkerAgent
from src.orchestration.state import GraphState


def worker_node(state: GraphState) -> dict[str, Any]:
    """Worker Agent 节点

    从新闻文章中提取情报微粒。
    """
    if not state.articles:
        return {
            "current_stage": "worker",
            "errors": ["无文章数据"],
        }

    try:
        agent = WorkerAgent()
        particles = agent.run(
            batch_size=10,
            incremental=False,
            dry_run=False,
        )

        return {
            "current_stage": "worker",
            "particles": particles,
        }
    except Exception as e:
        return {
            "current_stage": "worker",
            "errors": [f"Worker Agent 错误: {str(e)}"],
        }


def integrator_node(state: GraphState) -> dict[str, Any]:
    """Integrator Agent 节点

    执行实体对齐和图谱同步。
    """
    if not state.particles:
        return {
            "current_stage": "integrator",
            "errors": ["无情报微粒数据"],
        }

    try:
        agent = IntegratorAgent()
        result = agent.run(state.particles)

        # 从 result 中获取详细结果，避免重复调用
        alignment_results = result.pop("details", [])

        return {
            "current_stage": "integrator",
            "sync_result": result,
            "alignment_results": alignment_results,
        }
    except Exception as e:
        return {
            "current_stage": "integrator",
            "errors": [f"Integrator Agent 错误: {str(e)}"],
        }


def master_node(state: GraphState) -> dict[str, Any]:
    """Master Agent 节点

    执行风险穿透分析和报告生成。
    """
    if not state.query:
        # 无查询时，对第一个实体进行分析
        if state.particles:
            entities = set()
            for p in state.particles:
                for node in p.graph_updates.nodes:
                    entities.add(node.label)
            target_entity = list(entities)[0] if entities else "未知实体"
        else:
            target_entity = "未知实体"
    else:
        target_entity = state.query

    try:
        agent = MasterAgent()
        report = agent.analyze(
            target_entity=target_entity,
            particles=state.particles,
        )

        return {
            "current_stage": "master",
            "report": report.to_dict(),
            "risk_assessment": {
                "target": target_entity,
                "risk_level": report.risk_level,
                "risk_score": report.risk_score,
            },
        }
    except Exception as e:
        return {
            "current_stage": "master",
            "errors": [f"Master Agent 错误: {str(e)}"],
        }


def critic_node(state: GraphState) -> dict[str, Any]:
    """Critic Agent 节点

    执行事实核查。
    """
    if not state.report:
        return {
            "current_stage": "critic",
            "errors": ["无报告数据"],
        }

    try:
        agent = CriticAgent()
        result = agent.verify(
            report=state.report,
            particles=state.particles,
        )

        return {
            "current_stage": "critic",
            "verification_result": result.to_dict(),
            "verification_passed": result.passed,
            "retry_count": state.retry_count + 1,
        }
    except Exception as e:
        return {
            "current_stage": "critic",
            "errors": [f"Critic Agent 错误: {str(e)}"],
        }


def final_node(state: GraphState) -> dict[str, Any]:
    """最终节点

    生成最终输出。
    """
    final_output = {
        "report": state.report,
        "risk_assessment": state.risk_assessment,
        "verification": {
            "passed": state.verification_passed,
            "retry_count": state.retry_count,
            "issues": state.verification_result.get("issues", []),
        },
        "particles_count": len(state.particles),
        "errors": state.errors,
    }

    return {
        "current_stage": "final",
        "final_output": final_output,
    }
