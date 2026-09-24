from __future__ import annotations

from pathlib import Path

from local_agent_orchestrator.core.config import load_settings
from local_agent_orchestrator.models.plan import ExecutionPlan
from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.checkpointed_executor import (
    execute_checkpointed_task,
)
from local_agent_orchestrator.services.finalizer import finalize_run
from local_agent_orchestrator.services.git_workspace import GitWorkspace
from local_agent_orchestrator.services.plan_runner import (
    AUTO_EXECUTABLE_KINDS,
    APPROVAL_ONLY_KINDS,
    EXPLICIT_EXECUTABLE_KINDS,
    PlanExecutionError,
    PlanRunResult,
    _approval_required,
    finalize_plan_run,
    _mark_remaining_after_failure,
    _record_verification_metadata,
    _run_explicit_task,
    _validated_plan,
    _waiting_result,
)
from local_agent_orchestrator.services.run_state import RunStateManager


def approve_waiting_task(
    run_id: str,
    *,
    runs_dir: str | Path = "runs",
    task_id: str | None = None,
) -> str:
    manager = RunStateManager(runs_dir)
    state = manager.load(run_id)

    target = task_id or state.current_task

    if target is None:
        raise RuntimeError("Run has no task waiting for approval.")

    manager.approve_task(state, target)
    return target


def resume_execution_plan(
    run_id: str,
    workspace_root: str | Path,
    test_command: list[str],
    *,
    runs_dir: str | Path = "runs",
    analytics_dir: str | Path = ".agent/analytics",
) -> PlanRunResult:
    settings = load_settings()
    manager = RunStateManager(runs_dir)
    state = manager.load(run_id)
    if state.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        raise PlanExecutionError(
            "Run must be approved and pending, or be an interrupted running run, before it can be resumed."
        )
    lease = manager.acquire_execution_lease(run_id)
    try:
        return _resume_execution_plan(
            run_id, workspace_root, test_command, runs_dir, analytics_dir,
            settings, manager, state,
        )
    finally:
        manager.release_execution_lease(lease)


def _resume_execution_plan(
    run_id: str,
    workspace_root: str | Path,
    test_command: list[str],
    runs_dir: str | Path,
    analytics_dir: str | Path,
    settings,
    manager: RunStateManager,
    state: RunState,
) -> PlanRunResult:

    if not state.agent_branch:
        raise PlanExecutionError("Run does not have a recorded agent branch.")

    git = GitWorkspace(workspace_root)
    git.assert_clean()
    git.switch_branch(state.agent_branch)

    plan_path = manager.get_run_dir(run_id) / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"Saved plan not found for run: {run_id}")

    plan = ExecutionPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )

    if len(plan.tasks) != len(state.tasks):
        raise PlanExecutionError("Saved plan and run state task counts do not match.")

    validated = _validated_plan(
        plan,
        [task.id for task in state.tasks],
    )
    completed_ids = {
        effective_id
        for effective_id, task_state in zip(
            validated.effective_ids,
            state.tasks,
            strict=True,
        )
        if task_state.status == TaskStatus.PASSED
    }
    state_by_id = {
        effective_id: task_state
        for effective_id, task_state in zip(
            validated.effective_ids,
            state.tasks,
            strict=True,
        )
    }

    commits: list[str] = []
    completed_tasks = len(completed_ids)
    passed = True

    for index in validated.order:
        plan_task = plan.tasks[index]
        task_state = state.tasks[index]
        effective_id = validated.effective_ids[index]

        if task_state.status == TaskStatus.PASSED:
            continue
        if task_state.status in {
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
            TaskStatus.SKIPPED,
        }:
            raise PlanExecutionError(
                f"Cannot resume {task_state.status.value} task {effective_id}."
            )

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
            result = execute_checkpointed_task(
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
                state.tasks,
                validated.effective_ids,
                validated.order,
                effective_id,
            )
            passed = False
            break

        completed_ids.add(effective_id)
        completed_tasks += 1

    passed = passed and completed_tasks == len(plan.tasks)
    passed, finalization = finalize_plan_run(
        state,
        manager,
        passed,
        analytics_dir,
        finalizer=finalize_run,
    )

    return PlanRunResult(
        run_id=run_id,
        passed=passed,
        completed_tasks=completed_tasks,
        total_tasks=len(plan.tasks),
        commits=commits,
        run_dir=manager.get_run_dir(run_id),
        analytics_path=finalization.analytics_path if finalization else None,
        retrospective_path=finalization.retrospective_path if finalization else None,
    )
