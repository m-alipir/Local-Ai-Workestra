from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from local_agent_orchestrator.core.config import load_settings
from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.models.task import RunState, TaskState, TaskStatus
from local_agent_orchestrator.models.trajectory import TrajectoryEvent
from local_agent_orchestrator.services.checkpointed_executor import (
    CheckpointedTaskResult,
    execute_checkpointed_task,
)
from local_agent_orchestrator.services.finalizer import (
    FinalizationResult,
    finalize_run,
)
from local_agent_orchestrator.services.git_workspace import GitWorkspace
from local_agent_orchestrator.services.plan_task_executor import (
    PlanTaskExecution,
    execute_review_task,
    execute_test_task,
)
from local_agent_orchestrator.services.plan_validation import (
    PlanValidationError,
    ValidatedPlan,
    validate_plan,
)
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.trajectory import append_trajectory_event


class PlanExecutionError(RuntimeError):
    pass


AUTO_EXECUTABLE_KINDS = {"code", "docs"}
EXPLICIT_EXECUTABLE_KINDS = {"test", "review"}
APPROVAL_ONLY_KINDS = {"deploy", "manual"}


@dataclass(slots=True)
class PlanRunResult:
    run_id: str
    passed: bool
    completed_tasks: int
    total_tasks: int
    commits: list[str]
    run_dir: Path
    analytics_path: Path | None
    retrospective_path: Path | None
    waiting_for_approval: bool = False
    waiting_task_id: str | None = None


def _validated_plan(
    plan: ExecutionPlan,
    generated_ids: list[str],
) -> ValidatedPlan:
    try:
        return validate_plan(plan, generated_ids)
    except PlanValidationError as exc:
        raise PlanExecutionError(str(exc)) from exc


def _approval_required(task: PlanTask) -> bool:
    return (
        task.requires_approval
        or task.risk in {"high", "critical"}
        or task.kind in APPROVAL_ONLY_KINDS
    )


def _record_event(
    state: RunState,
    manager: RunStateManager,
    task_id: str,
    event: str,
    *,
    passed: bool | None = None,
    detail: str | None = None,
) -> None:
    append_trajectory_event(
        manager.get_run_dir(state.run_id),
        TrajectoryEvent(
            run_id=state.run_id,
            task_id=task_id,
            event=event,
            passed=passed,
            detail=detail,
        ),
    )


def _record_verification_metadata(
    state: RunState,
    manager: RunStateManager,
    task: PlanTask,
    task_state: TaskState,
) -> None:
    if not task.verification:
        return

    _record_event(
        state,
        manager,
        task_state.id,
        "verification_metadata",
        detail=(
            "Informational plan metadata was not executed as a shell command. "
            "The trusted global test command is the only executable verifier. "
            + "; ".join(task.verification)
        ),
    )


def _mark_remaining_after_failure(
    state: RunState,
    manager: RunStateManager,
    plan: ExecutionPlan,
    task_states: list[TaskState],
    effective_ids: tuple[str, ...],
    order: tuple[int, ...],
    failed_id: str,
) -> None:
    blocked_ids = {failed_id}

    for index in order:
        task_state = task_states[index]
        effective_id = effective_ids[index]
        if effective_id == failed_id:
            continue
        if task_state.status != TaskStatus.PENDING:
            continue

        dependencies = plan.tasks[index].depends_on
        if any(dependency in blocked_ids for dependency in dependencies):
            manager.mark_blocked(
                state,
                task_state.id,
                f"Blocked by unsuccessful dependency: {failed_id}.",
            )
            blocked_ids.add(effective_id)
        else:
            manager.mark_skipped(
                state,
                task_state.id,
                "Skipped after an earlier task failed.",
            )


def _run_explicit_task(
    state: RunState,
    manager: RunStateManager,
    task: PlanTask,
    task_state: TaskState,
    workspace_root: str | Path,
    test_command: list[str],
) -> PlanTaskExecution:
    manager.update_task(state, task_state.id, TaskStatus.RUNNING)
    _record_event(
        state,
        manager,
        task_state.id,
        "task_started",
        detail=task.description,
    )

    if task.kind == "test":
        result = execute_test_task(workspace_root, test_command)
    elif task.kind == "review":
        result = execute_review_task(workspace_root, task.description)
    else:
        raise PlanExecutionError(
            f"Task kind {task.kind!r} has no explicit executor."
        )

    manager.set_verification_status(
        state,
        task_state.id,
        result.verification_status,
    )

    if result.passed:
        manager.update_task(state, task_state.id, TaskStatus.PASSED)
    else:
        error = result.result.stderr.strip() or result.result.stdout.strip()
        manager.update_task(
            state,
            task_state.id,
            TaskStatus.FAILED,
            error=error or f"Task exited with code {result.result.returncode}",
        )

    _record_event(
        state,
        manager,
        task_state.id,
        "task_completed",
        passed=result.passed,
        detail=(
            result.detail
            or result.result.stderr.strip()
            or result.result.stdout.strip()
        ),
    )
    return result


def _waiting_result(
    state: RunState,
    manager: RunStateManager,
    task_state: TaskState,
    total_tasks: int,
    completed_tasks: int,
    commits: list[str],
) -> PlanRunResult:
    return PlanRunResult(
        run_id=state.run_id,
        passed=False,
        completed_tasks=completed_tasks,
        total_tasks=total_tasks,
        commits=commits,
        run_dir=manager.get_run_dir(state.run_id),
        analytics_path=None,
        retrospective_path=None,
        waiting_for_approval=True,
        waiting_task_id=task_state.id,
    )


def finalize_plan_run(
    state: RunState,
    manager: RunStateManager,
    passed: bool,
    analytics_dir: str | Path,
    *,
    finalizer: Callable[..., FinalizationResult] = finalize_run,
) -> tuple[bool, FinalizationResult | None]:
    """Finalize after the same durable running state for new and resumed runs."""
    run_dir = manager.get_run_dir(state.run_id)
    state.status = TaskStatus.RUNNING
    manager.save(state)
    append_trajectory_event(
        run_dir,
        TrajectoryEvent(
            run_id=state.run_id,
            task_id=state.current_task or "run",
            event="finalization_started",
            passed=None,
            detail="Analytics and retrospective finalization started.",
        ),
    )
    try:
        result = finalizer(
            run_id=state.run_id,
            run_dir=run_dir,
            analytics_dir=analytics_dir,
        )
    except Exception as exc:
        append_trajectory_event(
            run_dir,
            TrajectoryEvent(
                run_id=state.run_id,
                task_id=state.current_task or "run",
                event="finalization_failed",
                passed=False,
                detail=str(exc),
            ),
        )
        manager.finish_run(state, False)
        return False, None
    manager.finish_run(state, passed)
    return passed, result


def run_execution_plan(
    plan: ExecutionPlan,
    workspace_root: str | Path,
    test_command: list[str],
    runs_dir: str | Path | None = None,
    analytics_dir: str | Path = ".agent/analytics",
    *,
    plan_id: str | None = None,
    compiled_revision: int | None = None,
    compiled_digest: str | None = None,
    source_digest: str | None = None,
    compiled_at: datetime | None = None,
) -> PlanRunResult:
    settings = load_settings()
    manager = RunStateManager(runs_dir or settings.paths.runs)
    run_id = manager.new_run_id()
    lease = manager.acquire_execution_lease(run_id)
    try:
        return _run_execution_plan(
            plan, workspace_root, test_command, runs_dir, analytics_dir, run_id,
            plan_id=plan_id, compiled_revision=compiled_revision,
            compiled_digest=compiled_digest, source_digest=source_digest,
            compiled_at=compiled_at,
        )
    finally:
        manager.release_execution_lease(lease)


def _run_execution_plan(
    plan: ExecutionPlan,
    workspace_root: str | Path,
    test_command: list[str],
    runs_dir: str | Path | None,
    analytics_dir: str | Path,
    run_id: str,
    *,
    plan_id: str | None = None,
    compiled_revision: int | None = None,
    compiled_digest: str | None = None,
    source_digest: str | None = None,
    compiled_at: datetime | None = None,
) -> PlanRunResult:
    settings = load_settings()
    manager = RunStateManager(runs_dir or settings.paths.runs)
    state = manager.create_run(plan.request, run_id=run_id)
    state.plan_id = plan_id
    state.compiled_revision = compiled_revision
    state.compiled_digest = compiled_digest
    state.source_digest = source_digest
    state.compiled_at = compiled_at
    manager.save(state)

    plan_path = manager.get_run_dir(state.run_id) / "plan.json"
    plan_path.write_text(
        json.dumps(
            plan.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    generated_ids = [
        f"task-{index:03d}"
        for index, _ in enumerate(plan.tasks, start=1)
    ]
    validated = _validated_plan(plan, generated_ids)

    git = GitWorkspace(workspace_root)
    git.assert_clean()
    state.base_branch = git.current_branch()
    state.agent_branch = git.create_agent_branch(state.run_id)
    manager.save(state)

    task_states = [
        manager.add_task(state, task.description, task.verification)
        for task in plan.tasks
    ]

    state_by_id = {
        effective_id: task_state
        for effective_id, task_state in zip(
            validated.effective_ids,
            task_states,
            strict=True,
        )
    }
    commits: list[str] = []
    completed_tasks = 0
    passed = True

    for index in validated.order:
        plan_task = plan.tasks[index]
        task_state = task_states[index]
        effective_id = validated.effective_ids[index]

        if task_state.status == TaskStatus.PASSED:
            completed_tasks += 1
            continue

        missing_dependencies = [
            dependency
            for dependency in plan_task.depends_on
            if state_by_id[dependency].status != TaskStatus.PASSED
        ]
        if missing_dependencies:
            manager.mark_blocked(
                state,
                task_state.id,
                "Required dependency did not complete successfully: "
                + ", ".join(missing_dependencies),
            )
            _mark_remaining_after_failure(
                state,
                manager,
                plan,
                task_states,
                validated.effective_ids,
                validated.order,
                missing_dependencies[0],
            )
            passed = False
            break

        _record_verification_metadata(
            state,
            manager,
            plan_task,
            task_state,
        )

        if _approval_required(plan_task) and not task_state.approval_granted:
            manager.mark_waiting_for_approval(state, task_state.id)
            return _waiting_result(
                state,
                manager,
                task_state,
                len(plan.tasks),
                completed_tasks,
                commits,
            )

        if plan_task.kind in APPROVAL_ONLY_KINDS:
            manager.mark_waiting_for_approval(state, task_state.id)
            return _waiting_result(
                state,
                manager,
                task_state,
                len(plan.tasks),
                completed_tasks,
                commits,
            )

        if plan_task.kind in AUTO_EXECUTABLE_KINDS:
            result: CheckpointedTaskResult = execute_checkpointed_task(
                state=state,
                manager=manager,
                task_id=task_state.id,
                task_description=plan_task.description,
                workspace_root=workspace_root,
                test_command=test_command,
                retry_limit=settings.orchestrator.task_retry_limit,
                primary_scope=plan_task.primary_scope,
                discouraged_scope=plan_task.discouraged_scope,
                forbidden_scope=plan_task.forbidden_scope,
            )
            if result.commit:
                commits.append(result.commit)
            task_passed = result.execution.passed
            if task_passed and task_state.status != TaskStatus.PASSED:
                manager.update_task(state, task_state.id, TaskStatus.PASSED)
            elif not task_passed and task_state.status == TaskStatus.PENDING:
                manager.update_task(
                    state,
                    task_state.id,
                    TaskStatus.FAILED,
                    error="Checkpointed task failed.",
                )
        elif plan_task.kind in EXPLICIT_EXECUTABLE_KINDS:
            explicit_result = _run_explicit_task(
                state,
                manager,
                plan_task,
                task_state,
                workspace_root,
                test_command,
            )
            task_passed = explicit_result.passed
        else:
            raise PlanExecutionError(
                f"Task kind {plan_task.kind!r} is unsupported and cannot execute."
            )

        if not task_passed:
            _mark_remaining_after_failure(
                state,
                manager,
                plan,
                task_states,
                validated.effective_ids,
                validated.order,
                effective_id,
            )
            passed = False
            break

        completed_tasks += 1

    passed = passed and completed_tasks == len(plan.tasks)
    passed, finalization = finalize_plan_run(
        state,
        manager,
        passed,
        analytics_dir,
        finalizer=finalize_run,
    )
    run_dir = manager.get_run_dir(state.run_id)

    return PlanRunResult(
        run_id=state.run_id,
        passed=passed,
        completed_tasks=completed_tasks,
        total_tasks=len(plan.tasks),
        commits=commits,
        run_dir=run_dir,
        analytics_path=finalization.analytics_path if finalization else None,
        retrospective_path=finalization.retrospective_path if finalization else None,
    )
