from __future__ import annotations

from pathlib import Path

from local_agent_orchestrator.models.task import RunState, TaskStatus
from local_agent_orchestrator.models.trajectory import TrajectoryEvent
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.task_executor import (
    TaskExecutionResult,
    execute_task_with_retries,
)
from local_agent_orchestrator.services.trajectory import (
    append_trajectory_event,
)


def execute_tracked_task(
    state: RunState,
    manager: RunStateManager,
    task_id: str,
    task_description: str,
    workspace_root: str | Path,
    test_command: list[str],
    retry_limit: int = 2,
    primary_scope: list[str] | None = None,
    discouraged_scope: list[str] | None = None,
    forbidden_scope: list[str] | None = None,
    file_boundaries: list[str] | None = None,
) -> TaskExecutionResult:
    run_dir = manager.get_run_dir(state.run_id)

    def emit(data: dict) -> None:
        append_trajectory_event(
            run_dir,
            TrajectoryEvent(
                run_id=state.run_id,
                task_id=task_id,
                **data,
            ),
        )

    emit({
        "event": "task_started",
        "detail": task_description,
    })

    manager.update_task(
        state,
        task_id,
        TaskStatus.RUNNING,
    )

    try:
        result = execute_task_with_retries(
            task=task_description,
            workspace_root=workspace_root,
            test_command=test_command,
            retry_limit=retry_limit,
            primary_scope=primary_scope,
            discouraged_scope=discouraged_scope,
            forbidden_scope=forbidden_scope,
            file_boundaries=file_boundaries,
            event_callback=emit,
        )
    except Exception as exc:
        emit({
            "event": "task_exception",
            "passed": False,
            "detail": str(exc),
        })

        manager.update_task(
            state,
            task_id,
            TaskStatus.FAILED,
            error=str(exc),
        )
        raise

    for task in state.tasks:
        if task.id == task_id:
            task.attempts = result.attempts
            break

    if result.passed:
        manager.update_task(
            state,
            task_id,
            TaskStatus.PASSED,
        )

        emit({
            "event": "task_completed",
            "passed": True,
        })
    else:
        stdout = result.test_result.stdout.strip()
        stderr = result.test_result.stderr.strip()

        parts: list[str] = []

        if stdout:
            parts.append("STDOUT:\n" + stdout)

        if stderr:
            parts.append("STDERR:\n" + stderr)

        error = (
            "\n\n".join(parts)
            or f"Tests exited with code {result.test_result.returncode}"
        )

        manager.update_task(
            state,
            task_id,
            TaskStatus.FAILED,
            error=error,
        )

        emit({
            "event": "task_completed",
            "passed": False,
            "detail": error,
        })

    return result
