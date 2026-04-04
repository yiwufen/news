"""
PipelineContext 数据结构单元测试。
"""

from datetime import date

from src.intent.models import IntentType, QueryFilters, TimeRange
from src.orchestration.state import PipelineContext, QueryInput, StageOutput


class TestQueryInput:
    """QueryInput 测试。"""

    def test_creation_with_defaults(self):
        inp = QueryInput(raw_query="查看小米过去一年")
        assert inp.raw_query == "查看小米过去一年"
        assert inp.entities == []
        assert inp.time_range is None
        assert inp.intent is None

    def test_creation_with_all_fields(self):
        time_range = TimeRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        filters = QueryFilters(event_types=["policy_sanction"])

        inp = QueryInput(
            raw_query="查看小米过去一年的政策事件",
            entities=["小米集团"],
            time_range=time_range,
            intent=IntentType.ENTITY_TIMELINE,
            filters=filters,
        )

        assert inp.raw_query == "查看小米过去一年的政策事件"
        assert inp.entities == ["小米集团"]
        assert inp.time_range is not None
        assert inp.time_range.start == date(2025, 1, 1)
        assert inp.intent == IntentType.ENTITY_TIMELINE
        assert inp.filters.event_types == ["policy_sanction"]

    def test_to_dict(self):
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
    """StageOutput 测试。"""

    def test_success_output(self):
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
        output = StageOutput(
            stage_name="intent_parse",
            success=False,
            errors=["无用户查询", "解析失败"],
        )

        assert output.success is False
        assert len(output.errors) == 2
        assert "无用户查询" in output.errors

    def test_factory_methods(self):
        success_output = StageOutput.ok(
            stage_name="summary",
            data={"total_count": 10},
            duration_ms=500,
        )
        assert success_output.success is True
        assert success_output.data["total_count"] == 10

        failure_output = StageOutput.failure(
            stage_name="critic",
            errors=["核查失败"],
        )
        assert failure_output.success is False
        assert failure_output.errors == ["核查失败"]

    def test_to_dict(self):
        output = StageOutput(
            stage_name="worker",
            success=True,
            data={"knowledge_units": []},
            errors=[],
            duration_ms=200,
        )

        result = output.to_dict()
        assert result["stage_name"] == "worker"
        assert result["success"] is True
        assert result["duration_ms"] == 200


class TestPipelineContext:
    """PipelineContext 测试。"""

    def test_creation_with_defaults(self):
        ctx = PipelineContext()

        assert ctx.request_id != ""
        assert len(ctx.request_id) == 8
        assert ctx.input is None
        assert ctx.stages == {}
        assert ctx.current_stage == "init"

    def test_creation_with_input(self):
        inp = QueryInput(raw_query="测试查询", entities=["小米"])
        ctx = PipelineContext(input=inp, graph_enabled=False)

        assert ctx.input is not None
        assert ctx.input.raw_query == "测试查询"
        assert ctx.graph_enabled is False

    def test_add_stage(self):
        ctx = PipelineContext()

        output = StageOutput.ok(
            stage_name="intent_parse",
            data={"intent": "ENTITY_TIMELINE"},
        )
        ctx.add_stage(output)

        assert "intent_parse" in ctx.stages
        assert ctx.current_stage == "intent_parse"

    def test_add_error(self):
        ctx = PipelineContext()
        ctx.add_error("retrieval", "检索失败")

        assert "retrieval" in ctx.stages
        assert ctx.stages["retrieval"].success is False
        assert "检索失败" in ctx.stages["retrieval"].errors

    def test_get_knowledge_units_from_retrieval(self):
        ctx = PipelineContext()
        ctx.add_stage(
            StageOutput.ok(
                stage_name="retrieval",
                data={"knowledge_units": []},
            )
        )

        knowledge_units = ctx.get_knowledge_units()
        assert knowledge_units == []

    def test_get_knowledge_units_from_worker(self):
        ctx = PipelineContext()
        ctx.add_stage(
            StageOutput.ok(
                stage_name="worker",
                data={"knowledge_units": []},
            )
        )

        knowledge_units = ctx.get_knowledge_units()
        assert knowledge_units == []

    def test_get_entities(self):
        ctx = PipelineContext()
        ctx.add_stage(
            StageOutput.ok(
                stage_name="retrieval",
                data={"entities": [{"entity_id": "ent-1"}]},
            )
        )

        entities = ctx.get_entities()
        assert entities == [{"entity_id": "ent-1"}]

    def test_get_event_clusters(self):
        ctx = PipelineContext()
        ctx.add_stage(
            StageOutput.ok(
                stage_name="integrator",
                data={"event_clusters": [{"cluster_id": "clu-1"}]},
            )
        )

        clusters = ctx.get_event_clusters()
        assert clusters == [{"cluster_id": "clu-1"}]

    def test_get_stage_data(self):
        ctx = PipelineContext()
        ctx.add_stage(
            StageOutput.ok(
                stage_name="summary",
                data={"total_count": 2},
            )
        )

        summary = ctx.get_stage_data("summary")
        assert summary["total_count"] == 2

    def test_get_stage_data_not_found(self):
        ctx = PipelineContext()
        summary = ctx.get_stage_data("summary")
        assert summary == {}

    def test_is_verification_passed(self):
        ctx = PipelineContext()

        assert ctx.is_verification_passed() is False

        ctx.add_stage(
            StageOutput.ok(
                stage_name="critic",
                data={"passed": True},
            )
        )
        assert ctx.is_verification_passed() is True

        ctx.add_stage(
            StageOutput.ok(
                stage_name="critic",
                data={"passed": False},
            )
        )
        assert ctx.is_verification_passed() is False

    def test_to_dict(self):
        inp = QueryInput(raw_query="测试", intent=IntentType.ENTITY_TIMELINE)
        ctx = PipelineContext(input=inp)
        ctx.add_stage(
            StageOutput.ok(
                stage_name="intent_parse",
                data={},
            )
        )

        result = ctx.to_dict()
        assert result["request_id"] == ctx.request_id
        assert result["input"]["raw_query"] == "测试"
        assert "intent_parse" in result["stages"]
        assert result["current_stage"] == "intent_parse"


class TestPipelineContextIntegration:
    """PipelineContext 集成场景测试。"""

    def test_full_flow_simulation(self):
        inp = QueryInput(
            raw_query="查看恒大集团相关事件",
            entities=["恒大集团"],
            intent=IntentType.ENTITY_TIMELINE,
        )
        ctx = PipelineContext(input=inp)

        ctx.add_stage(
            StageOutput.ok(
                stage_name="intent_parse",
                data={"confidence": 0.95},
                duration_ms=100,
            )
        )

        ctx.add_stage(
            StageOutput.ok(
                stage_name="retrieval",
                data={
                    "knowledge_units": [],
                    "entities": [],
                    "event_clusters": [],
                    "total_count": 0,
                },
                duration_ms=50,
            )
        )

        ctx.add_stage(
            StageOutput.ok(
                stage_name="integrator",
                data={"entities": [], "event_clusters": []},
                duration_ms=300,
            )
        )

        ctx.add_stage(
            StageOutput.ok(
                stage_name="summary",
                data={"total_count": 0, "source": "knowledge_base"},
                duration_ms=500,
            )
        )

        ctx.add_stage(
            StageOutput.ok(
                stage_name="critic",
                data={"passed": True},
                duration_ms=200,
            )
        )

        assert ctx.is_verification_passed() is True
        assert ctx.current_stage == "critic"

        summary = ctx.get_stage_data("summary")
        assert summary["source"] == "knowledge_base"

        result = ctx.to_dict()
        assert len(result["stages"]) == 5
        total_duration = sum(s["duration_ms"] for s in result["stages"].values())
        assert total_duration == 1150
