"""Task execution routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_orchestrator
from src.api.models.requests import ExecuteChainRequest, ExecuteTaskRequest
from src.api.models.responses import TaskResultResponse
from src.session import SessionOrchestrator, TaskDefinition

router = APIRouter(prefix="/sessions/{session_id}/tasks", tags=["Task"])


def _build_task_result_response(result) -> TaskResultResponse:
    """Build TaskResultResponse from TaskResult."""
    return TaskResultResponse(
        task_id=result.task_id,
        skill_type=result.skill_type,
        state=result.state.value,
        started_at=result.started_at,
        completed_at=result.completed_at,
        output=result.output,
        errors=result.errors,
        duration_ms=result.duration_ms,
    )


@router.post("", response_model=TaskResultResponse)
async def execute_task(
    session_id: str,
    request: ExecuteTaskRequest,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> TaskResultResponse:
    """Execute a single task within a session."""
    try:
        result = await orchestrator.execute_task(
            session_id=session_id,
            skill_type=request.skill_type,
            query=request.query,
            use_context=request.use_context,
            input_variables=request.input_variables,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return _build_task_result_response(result)


@router.post("/chain", response_model=list[TaskResultResponse])
async def execute_chain(
    session_id: str,
    request: ExecuteChainRequest,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> list[TaskResultResponse]:
    """Execute a chain of tasks within a session."""
    tasks = [
        TaskDefinition(
            task_id=t.task_id,
            skill_type=t.skill_type,
            query=t.query,
            depends_on=t.depends_on,
            input_mapping=t.input_mapping,
            condition=t.condition,
        )
        for t in request.tasks
    ]

    try:
        results = await orchestrator.execute_chain(
            session_id=session_id,
            tasks=tasks,
            parallel=request.parallel,
            stop_on_failure=request.stop_on_failure,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return [_build_task_result_response(r) for r in results]
