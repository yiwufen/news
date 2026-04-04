"""
PipelineContext 数据结构单元测试

测试 QueryInput、StageOutput、PipelineContext 的核心功能。
"""

from datetime import date, datetime, timedelta

import pytest

from src.intent.models import IntentType, QueryFilters, TimeRange
from src.orchestration.state import PipelineContext, QueryInput, StageOutput


class TestQueryInput:
    """QueryInput 测试"""

    def test_creation_with_defaults(self):
        """测试默认值创建"""
        inp = QueryInput(raw_query="查看小米过去一年")
        assert inp.raw_query == "查看小米过去一年"
        assert inp.entities == []
        assert inp.time_range is None
        assert inp.intent is None

    def test_creation_with_all_fields(self):
        """测试完整字段创建"""
        time_range = TimeRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        filters = QueryFilters(event_types=["POLICY_SANCTION"])

        inp = QueryInput(
            raw_query="查看小米过去一年的政策风险",
            entities=["小米集团"],
            time_range=time_range,
            intent=IntentType.ENTITY_TIMELINE,
            filters=filters,
        )

        assert inp.raw_query == "查看小米过去一年的政策风险"
        assert inp.entities == ["小米集团"]
        assert inp.time_range.start == date(2025, 1, 1)
        assert inp.intent == IntentType.ENTITY_TIMELINE
        assert inp.filters.event_types == ["POLICY_SANCTION"]

    def test_to_dict(self):
        """测试字典转换"""
        time_range = TimeRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        inp = QueryInput(
            raw_query="测试查询",
            entities=["实体A"],
            time_range=time_range,
            intent=IntentType.RISK_ASSESSMENT,
        )

        result = inp.to_dict()
        assert result["raw_query"] == "测试查询"
        assert result["entities"] == ["实体A"]
        assert result["time_range"]["start"] == "2025-01-01"
        assert result["intent"] == "RISK_ASSESSMENT"


class TestStageOutput:
    """StageOutput 测试"""

    def test_success_output(self):
        """测试成功输出"""
        output = StageOutput(
            stage_name="retrieval",
            success=True,
            data={"count": 10},
            duration_ms=150,
        )

        assert output.stage_name == "retrieval"
        assert output.success is True
        assert output.data["count"] == 10
        assert output.duration_ms == 150
        assert output.errors == []

    def test_failure_output(self):
        """测试失败输出"""
        output = StageOutput(
            stage_name="intent_parse",
            success=False,
            errors=["无用户查询", "解析失败"],
        )

        assert output.success is False
        assert len(output.errors) == 2
        assert "无用户查询" in output.errors

    def test_factory_methods(self):
        """测试工厂方法"""
        # success 工厂方法
        success_output = StageOutput.ok(
            stage_name="master",
            data={"risk_level": "HIGH"},
            duration_ms=500,
        )
        assert success_output.success is True
        assert success_output.data["risk_level"] == "HIGH"

        # failure 工厂方法
        failure_output = StageOutput.failure(
            stage_name="critic",
            errors=["核查失败"],
        )
        assert failure_output.success is False
        assert failure_output.errors == ["核查失败"]

    def test_to_dict(self):
        """测试字典转换"""
        output = StageOutput(
            stage_name="worker",
            success=True,
            data={"particles": []},
            errors=[],
            duration_ms=200,
        )

        result = output.to_dict()
        assert result["stage_name"] == "worker"
        assert result["success"] is True
        assert result["duration_ms"] == 200


class TestPipelineContext:
    """PipelineContext 测试"""

    def test_creation_with_defaults(self):
        """测试默认值创建"""
        ctx = PipelineContext()

        assert ctx.request_id != ""
        assert len(ctx.request_id) == 8
        assert ctx.input is None
        assert ctx.stages == {}
        assert ctx.current_stage == "init"

    def test_creation_with_input(self):
        """测试带输入创建"""
        inp = QueryInput(raw_query="测试查询", entities=["小米"])
        ctx = PipelineContext(input=inp, graph_enabled=False)

        assert ctx.input is not None
        assert ctx.input.raw_query == "测试查询"
        assert ctx.graph_enabled is False

    def test_add_stage(self):
        """测试添加阶段输出"""
        ctx = PipelineContext()

        output = StageOutput.ok(
            stage_name="intent_parse",
            data={"intent": "ENTITY_TIMELINE"},
        )
        ctx.add_stage(output)

        assert "intent_parse" in ctx.stages
        assert ctx.current_stage == "intent_parse"

    def test_add_error(self):
        """测试添加错误"""
        ctx = PipelineContext()
        ctx.add_error("retrieval", "检索失败")

        assert "retrieval" in ctx.stages
        assert ctx.stages["retrieval"].success is False
        assert "检索失败" in ctx.stages["retrieval"].errors

    def test_get_particles_from_retrieval(self):
        """测试从检索结果获取微粒"""
        ctx = PipelineContext()
        ctx.add_stage(StageOutput.ok(
            stage_name="retrieval",
            data={"particles": []},  # 空列表
        ))

        particles = ctx.get_particles()
        assert particles == []

    def test_get_particles_from_worker(self):
        """测试从 Worker 结果获取微粒"""
        ctx = PipelineContext()
        ctx.add_stage(StageOutput.ok(
            stage_name="worker",
            data={"particles": []},
        ))

        particles = ctx.get_particles()
        assert particles == []

    def test_get_report(self):
        """测试获取报告"""
        ctx = PipelineContext()
        ctx.add_stage(StageOutput.ok(
            stage_name="master",
            data={"risk_level": "HIGH", "risk_score": 0.8},
        ))

        report = ctx.get_report()
        assert report["risk_level"] == "HIGH"
        assert report["risk_score"] == 0.8

    def test_get_report_not_found(self):
        """测试获取不存在的报告"""
        ctx = PipelineContext()
        report = ctx.get_report()
        assert report == {}

    def test_is_verification_passed(self):
        """测试核查通过判断"""
        ctx = PipelineContext()

        # 未执行 Critic
        assert ctx.is_verification_passed() is False

        # Critic 通过
        ctx.add_stage(StageOutput.ok(
            stage_name="critic",
            data={"passed": True},
        ))
        assert ctx.is_verification_passed() is True

        # Critic 未通过
        ctx.add_stage(StageOutput.ok(
            stage_name="critic",
            data={"passed": False},
        ))
        assert ctx.is_verification_passed() is False

    def test_to_dict(self):
        """测试字典转换"""
        inp = QueryInput(raw_query="测试", intent=IntentType.ENTITY_TIMELINE)
        ctx = PipelineContext(input=inp)
        ctx.add_stage(StageOutput.ok(
            stage_name="intent_parse",
            data={},
        ))

        result = ctx.to_dict()
        assert result["request_id"] == ctx.request_id
        assert result["input"]["raw_query"] == "测试"
        assert "intent_parse" in result["stages"]
        assert result["current_stage"] == "intent_parse"


class TestPipelineContextIntegration:
    """PipelineContext 集成场景测试"""

    def test_full_flow_simulation(self):
        """模拟完整流程"""
        # 1. 创建上下文
        inp = QueryInput(
            raw_query="分析恒大集团的债务风险",
            entities=["恒大集团"],
            intent=IntentType.RISK_ASSESSMENT,
        )
        ctx = PipelineContext(input=inp)

        # 2. 意图解析
        ctx.add_stage(StageOutput.ok(
            stage_name="intent_parse",
            data={"confidence": 0.95},
            duration_ms=100,
        ))

        # 3. 检索
        ctx.add_stage(StageOutput.ok(
            stage_name="retrieval",
            data={"particles": [], "total_count": 0},
            duration_ms=50,
        ))

        # 4. Worker（无微粒时回退）
        ctx.add_stage(StageOutput.ok(
            stage_name="worker",
            data={"particles": []},
            duration_ms=2000,
        ))

        # 5. Integrator
        ctx.add_stage(StageOutput.ok(
            stage_name="integrator",
            data={"entities_created": 1, "edges_created": 0},
            duration_ms=300,
        ))

        # 6. Master
        ctx.add_stage(StageOutput.ok(
            stage_name="master",
            data={"risk_level": "HIGH", "risk_score": 0.85},
            duration_ms=500,
        ))

        # 7. Critic
        ctx.add_stage(StageOutput.ok(
            stage_name="critic",
            data={"passed": True},
            duration_ms=200,
        ))

        # 验证最终状态
        assert ctx.is_verification_passed() is True
        assert ctx.current_stage == "critic"

        # 验证报告
        report = ctx.get_report()
        assert report["risk_level"] == "HIGH"

        # 验证可追溯性
        result = ctx.to_dict()
        assert len(result["stages"]) == 6
        total_duration = sum(
            s["duration_ms"] for s in result["stages"].values()
        )
        assert total_duration == 3150
