"""
Pipeline 端到端测试

测试状态机的完整流程。
"""

import pytest

from src.intent.models import IntentType
from src.orchestration import PipelineContext, QueryInput, StageOutput, run_pipeline


class TestPipelineV2Basic:
    """Pipeline V2 基础测试"""

    def test_context_creation(self):
        """测试上下文创建"""
        ctx = PipelineContext(
            input=QueryInput(raw_query="测试查询"),
        )

        assert ctx.input is not None
        assert ctx.input.raw_query == "测试查询"
        assert ctx.current_stage == "init"

    def test_stage_output_success(self):
        """测试成功阶段输出"""
        output = StageOutput.ok(
            stage_name="test",
            data={"count": 5},
            duration_ms=100,
        )

        assert output.success is True
        assert output.data["count"] == 5

    def test_stage_output_failure(self):
        """测试失败阶段输出"""
        output = StageOutput.failure(
            stage_name="test",
            errors=["错误1", "错误2"],
        )

        assert output.success is False
        assert len(output.errors) == 2


class TestPipelineV2Routing:
    """Pipeline V2 路由测试"""

    def test_route_entity_timeline(self):
        """测试时间线路由"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(IntentType.ENTITY_TIMELINE)
        assert result == "entity_timeline_path"

    def test_route_risk_assessment(self):
        """测试风险评估路由"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(IntentType.RISK_ASSESSMENT)
        assert result == "risk_assessment_path"

    def test_route_relationship_query(self):
        """测试关系查询路由"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(IntentType.RELATIONSHIP_QUERY)
        assert result == "relationship_query_path"

    def test_route_comparative_analysis(self):
        """测试对比分析路由"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(IntentType.COMPARATIVE_ANALYSIS)
        assert result == "comparative_analysis_path"

    def test_route_event_impact(self):
        """测试事件影响路由"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(IntentType.EVENT_IMPACT)
        assert result == "event_impact_path"

    def test_route_none_returns_error(self):
        """测试空意图返回错误路径"""
        from src.routing.router import TaskRouter

        result = TaskRouter.route_by_intent(None)
        assert result == "error_path"


class TestPipelineV2CriticDecision:
    """Pipeline V2 Critic 决策测试"""

    def test_needs_critic_for_timeline(self):
        """测试时间线不需要 Critic"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_critic(IntentType.ENTITY_TIMELINE)
        assert result is False

    def test_needs_critic_for_comparative(self):
        """测试对比分析不需要 Critic"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_critic(IntentType.COMPARATIVE_ANALYSIS)
        assert result is False

    def test_needs_critic_for_risk_assessment(self):
        """测试风险评估需要 Critic"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_critic(IntentType.RISK_ASSESSMENT)
        assert result is True

    def test_needs_critic_for_event_impact(self):
        """测试事件影响需要 Critic"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_critic(IntentType.EVENT_IMPACT)
        assert result is True


class TestPipelineV2GraphSync:
    """Pipeline V2 图谱同步决策测试"""

    def test_needs_graph_for_relationship_query(self):
        """测试关系查询必须使用图谱"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_graph_sync(IntentType.RELATIONSHIP_QUERY, False)
        assert result is True  # 即使 graph_enabled=False，关系查询仍需要图谱

    def test_no_graph_for_timeline(self):
        """测试时间线不需要图谱"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_graph_sync(IntentType.ENTITY_TIMELINE, True)
        assert result is False

    def test_no_graph_for_comparative(self):
        """测试对比分析不需要图谱"""
        from src.routing.router import TaskRouter

        result = TaskRouter.needs_graph_sync(IntentType.COMPARATIVE_ANALYSIS, True)
        assert result is False

    def test_graph_for_risk_assessment(self):
        """测试风险评估根据配置决定"""
        from src.routing.router import TaskRouter

        result_enabled = TaskRouter.needs_graph_sync(IntentType.RISK_ASSESSMENT, True)
        result_disabled = TaskRouter.needs_graph_sync(IntentType.RISK_ASSESSMENT, False)

        assert result_enabled is True
        assert result_disabled is False


class TestPipelineV2Simulation:
    """Pipeline V2 流程模拟测试"""

    def test_full_flow_simulation(self):
        """模拟完整流程（不调用 LLM）"""
        # 创建上下文
        ctx = PipelineContext(
            input=QueryInput(
                raw_query="分析小米集团的风险",
                entities=["小米集团"],
                intent=IntentType.RISK_ASSESSMENT,
            ),
            graph_enabled=False,
        )

        # 模拟各阶段
        ctx.add_stage(StageOutput.ok(
            stage_name="intent_parse",
            data={"confidence": 0.95},
            duration_ms=50,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="retrieval",
            data={"particles": [], "source": "particles"},
            duration_ms=100,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="worker",
            data={"particles": [], "count": 0},
            duration_ms=2000,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="integrator",
            data={"entities_created": 0, "edges_created": 0},
            duration_ms=300,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="master",
            data={
                "report": {"risk_level": "MEDIUM"},
                "risk_level": "MEDIUM",
                "risk_score": 0.5,
            },
            duration_ms=500,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="critic",
            data={"passed": True, "issues": []},
            duration_ms=200,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="final",
            data={"report": {"risk_level": "MEDIUM"}},
            duration_ms=10,
        ))

        # 验证流程
        assert ctx.is_verification_passed() is True
        assert ctx.current_stage == "final"
        assert len(ctx.stages) == 7

        # 验证总耗时
        total_duration = sum(s.duration_ms for s in ctx.stages.values())
        assert total_duration == 3160

    def test_timeline_flow_simulation(self):
        """模拟时间线流程（短路，无需 Worker/Critic）"""
        ctx = PipelineContext(
            input=QueryInput(
                raw_query="查看小米过去一年",
                entities=["小米集团"],
                intent=IntentType.ENTITY_TIMELINE,
            ),
            graph_enabled=False,
        )

        # 时间线只需要 3 个阶段
        ctx.add_stage(StageOutput.ok(
            stage_name="intent_parse",
            data={},
            duration_ms=50,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="retrieval",
            data={"particles": [], "source": "particles"},
            duration_ms=100,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="timeline",
            data={"timeline": {"events": []}, "entity": "小米集团"},
            duration_ms=200,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="final",
            data={"timeline_data": {"events": []}},
            duration_ms=10,
        ))

        # 验证流程
        assert len(ctx.stages) == 4  # 只有 4 个阶段
        assert "worker" not in ctx.stages
        assert "critic" not in ctx.stages

    def test_comparative_analysis_flow_simulation(self):
        """模拟对比分析流程"""
        ctx = PipelineContext(
            input=QueryInput(
                raw_query="对比小米和华为的风险",
                entities=["小米集团", "华为"],
                intent=IntentType.COMPARATIVE_ANALYSIS,
            ),
            graph_enabled=False,
        )

        # 对比分析需要检索 + 比较，但不需要 Critic
        ctx.add_stage(StageOutput.ok(
            stage_name="intent_parse",
            data={},
            duration_ms=50,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="retrieval",
            data={"particles": [], "source": "particles"},
            duration_ms=100,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="comparative_analysis",
            data={
                "comparison_report": {"entities": ["小米集团", "华为"]},
                "entity_reports": {},
            },
            duration_ms=800,
        ))

        ctx.add_stage(StageOutput.ok(
            stage_name="final",
            data={"comparison_report": {"entities": ["小米集团", "华为"]}},
            duration_ms=10,
        ))

        # 验证流程
        assert len(ctx.stages) == 4
        assert "critic" not in ctx.stages
        assert "worker" not in ctx.stages
