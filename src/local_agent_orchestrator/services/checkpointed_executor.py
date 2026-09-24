from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from local_agent_orchestrator.core.config import load_models
from local_agent_orchestrator.models.metrics import TaskMetrics
from local_agent_orchestrator.models.security import SecurityReview
from local_agent_orchestrator.models.task import RunState, TaskStatus
from local_agent_orchestrator.models.trajectory import TrajectoryEvent
from local_agent_orchestrator.services.git_workspace import (
    GitWorkspace,
    GitWorkspaceError,
)
from local_agent_orchestrator.services.metrics import write_task_metrics
from local_agent_orchestrator.services.optimizer import (
    requires_optimization_review,
    run_optimization_review,
)
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.security import (
    requires_security_review,
    run_security_review,
)
from local_agent_orchestrator.services.task_executor import (
    TaskExecutionResult,
    execute_task_with_retries,
)
from local_agent_orchestrator.services.test_runner import CommandResult
from local_agent_orchestrator.services.trajectory import append_trajectory_event
from local_agent_orchestrator.services.tracked_executor import (
    execute_tracked_task,
)
from local_agent_orchestrator.services.workspace import Workspace


@dataclass(slots=True)
class CheckpointedTaskResult:
    execution: TaskExecutionResult
    commit: str | None
    metrics_path: Path
    security_review: SecurityReview | None
    optimization_review: str | None


def _security_fix_prompt(
    task: str,
    review: SecurityReview,
    workspace_root: str | Path,
    changed_files: list[str],
) -> str:
    findings = "\n".join(
        (
            f"- [{finding.severity.upper()}] {finding.title}: "
            f"{finding.description} FIX: {finding.recommendation}"
        )
        for finding in review.findings
        if finding.severity in ("high", "critical")
    )

    workspace = Workspace(workspace_root)
    current_files = ""

    for path in changed_files:
        if workspace.exists(path):
            current_files += (
                f"\n--- FILE: {path} ---\n"
                f"{workspace.read_text(path)}\n"
            )

    return (
        f"{task}\n\n"
        "SECURITY REVIEW FOUND BLOCKING ISSUES.\n"
        "Fix ONLY the concrete security findings below while preserving "
        "existing functionality.\n\n"
        f"FINDINGS:\n{findings}\n\n"
        f"CURRENT FILES:\n{current_files}"
    )


def _set_attempts(
    state: RunState,
    manager: RunStateManager,
    task_id: str,
    attempts: int,
) -> None:
    for task in state.tasks:
        if task.id == task_id:
            task.attempts = attempts
            manager.save(state)
            return


def _fail_post_edit_review(
    result: TaskExecutionResult,
    exc: Exception,
    *,
    git: GitWorkspace,
    state: RunState,
    manager: RunStateManager,
    task_id: str,
) -> None:
    error = f"Post-edit review failed: {type(exc).__name__}: {exc}"
    result.passed = False
    result.test_result = CommandResult(
        passed=False,
        returncode=125,
        stdout=result.test_result.stdout,
        stderr=error,
    )
    manager.update_task(state, task_id, TaskStatus.FAILED, error=error)
    append_trajectory_event(
        manager.get_run_dir(state.run_id),
        TrajectoryEvent(
            run_id=state.run_id,
            task_id=task_id,
            event="post_edit_review_failed",
            passed=False,
            detail=error,
            failure_class="review_failure",
        ),
    )
    try:
        git.rollback()
    except GitWorkspaceError as rollback_error:
        manager.update_task(
            state,
            task_id,
            TaskStatus.FAILED,
            error=f"{error} Rollback failed: {rollback_error}",
        )
        return
    append_trajectory_event(
        manager.get_run_dir(state.run_id),
        TrajectoryEvent(
            run_id=state.run_id,
            task_id=task_id,
            event="rollback",
            passed=True,
            detail="Rolled back post-edit review failure.",
        ),
    )


def execute_checkpointed_task(
    state: RunState,
    manager: RunStateManager,
    task_id: str,
    task_description: str,
    workspace_root: str | Path,
    test_command: list[str],
    retry_limit: int = 2,
    security_fix_limit: int = 1,
    primary_scope: list[str] | None = None,
    discouraged_scope: list[str] | None = None,
    forbidden_scope: list[str] | None = None,
    file_boundaries: list[str] | None = None,
) -> CheckpointedTaskResult:
    git = GitWorkspace(workspace_root)
    git.assert_clean()

    started_at = datetime.now(timezone.utc)
    start_clock = monotonic()

    commit: str | None = None
    security_review: SecurityReview | None = None
    optimization_review: str | None = None

    try:
        result = execute_tracked_task(
            state=state,
            manager=manager,
            task_id=task_id,
            task_description=task_description,
            workspace_root=workspace_root,
            test_command=test_command,
            retry_limit=retry_limit,
            primary_scope=primary_scope,
            discouraged_scope=discouraged_scope,
            forbidden_scope=forbidden_scope,
            file_boundaries=file_boundaries,
        )
    except Exception:
        git.rollback()
        raise

    if result.passed and requires_security_review(
        task_description,
        result.changed_files,
    ):
        try:
            security_review = run_security_review(
                task=task_description,
                changed_files=result.changed_files,
                workspace_root=workspace_root,
            )
        except Exception as exc:
            _fail_post_edit_review(
                result,
                exc,
                git=git,
                state=state,
                manager=manager,
                task_id=task_id,
            )

        security_round = 0

        while (
            result.passed
            and security_review is not None
            and security_review.has_blocking_findings
            and security_round < security_fix_limit
        ):
            security_round += 1

            try:
                fix_result = execute_task_with_retries(
                    task=_security_fix_prompt(
                        task_description,
                        security_review,
                        workspace_root,
                        result.changed_files,
                    ),
                    workspace_root=workspace_root,
                    test_command=test_command,
                    retry_limit=retry_limit,
                    primary_scope=primary_scope,
                    discouraged_scope=discouraged_scope,
                    forbidden_scope=forbidden_scope,
                    file_boundaries=file_boundaries,
                )
            except Exception as exc:
                _fail_post_edit_review(
                    result,
                    exc,
                    git=git,
                    state=state,
                    manager=manager,
                    task_id=task_id,
                )
                break

            result.attempts += fix_result.attempts
            result.changed_files = list(
                dict.fromkeys(
                    result.changed_files + fix_result.changed_files
                )
            )
            result.test_result = fix_result.test_result
            result.diagnoses.extend(fix_result.diagnoses)

            if not fix_result.passed:
                result.passed = False
                manager.update_task(
                    state,
                    task_id,
                    TaskStatus.FAILED,
                    error="Security fix failed tests.",
                )
                break

            try:
                security_review = run_security_review(
                    task=task_description,
                    changed_files=result.changed_files,
                    workspace_root=workspace_root,
                )
            except Exception as exc:
                _fail_post_edit_review(
                    result,
                    exc,
                    git=git,
                    state=state,
                    manager=manager,
                    task_id=task_id,
                )
                break

        if (
            result.passed
            and security_review is not None
            and security_review.has_blocking_findings
        ):
            result.passed = False

            manager.update_task(
                state,
                task_id,
                TaskStatus.FAILED,
                error="Blocking security findings remain.",
            )

    _set_attempts(
        state,
        manager,
        task_id,
        result.attempts,
    )

    if result.passed and requires_optimization_review(
        task_description,
        result.changed_files,
    ):
        try:
            optimization_review = run_optimization_review(
                task=task_description,
                changed_files=result.changed_files,
                workspace_root=workspace_root,
            )
        except Exception as exc:
            _fail_post_edit_review(
                result,
                exc,
                git=git,
                state=state,
                manager=manager,
                task_id=task_id,
            )

    if result.passed:
        try:
            commit = git.checkpoint(
                f"agent: {task_id} {task_description}"
            )
        except GitWorkspaceError as exc:
            result.passed = False
            result.test_result = CommandResult(
                passed=False,
                returncode=125,
                stdout=result.test_result.stdout,
                stderr=f"Checkpoint failed: {exc}",
            )
            manager.update_task(
                state,
                task_id,
                TaskStatus.FAILED,
                error=result.test_result.stderr,
            )
            git.rollback()
            append_trajectory_event(
                manager.get_run_dir(state.run_id),
                TrajectoryEvent(
                    run_id=state.run_id,
                    task_id=task_id,
                    event="checkpoint_failed",
                    model=result.accepted_model,
                    attempt=result.accepted_attempt,
                    passed=False,
                    detail=result.test_result.stderr,
                ),
            )
    else:
        git.rollback()

    if commit is not None:
        append_trajectory_event(
            manager.get_run_dir(state.run_id),
            TrajectoryEvent(
                run_id=state.run_id,
                task_id=task_id,
                event="checkpoint_created",
                model=result.accepted_model,
                attempt=result.accepted_attempt,
                passed=True,
                detail=(
                    f"commit={commit}; "
                    f"changed_files={','.join(result.changed_files)}"
                ),
            ),
        )

    finished_at = datetime.now(timezone.utc)

    models = load_models()

    model_reasoning = {
        name: model.reasoning
        for name, model in models.models.items()
    }

    metrics = TaskMetrics(
        task_id=task_id,
        description=task_description,
        started_at=started_at,
        finished_at=finished_at,
        duration_sec=monotonic() - start_clock,
        attempts=result.attempts,
        passed=result.passed,
        changed_files=result.changed_files,
        test_returncode=result.test_result.returncode,
        commit=commit,
        diagnoses=result.diagnoses,
        qwen_attempts=result.qwen_attempts,
        devstral_used=result.devstral_used,
        accepted_model=result.accepted_model,
        accepted_attempt=result.accepted_attempt,
        operation_failures=result.operation_failures,
        scope_reviews=result.scope_reviews,
        diagnosis_count=len(result.diagnoses),
        security_review_used=security_review is not None,
        optimization_review_used=optimization_review is not None,
        model_reasoning=model_reasoning,
        security_review=security_review,
        optimization_review=optimization_review,
        baseline_returncode=(
            result.baseline_result.returncode
            if result.baseline_result is not None
            else None
        ),
        baseline_passed=(
            result.baseline_result.passed
            if result.baseline_result is not None
            else None
        ),
        baseline_failure_identities=result.baseline_failure_identities,
        post_change_failure_identities=result.post_change_failure_identities,
        verification_classification=result.verification_classification,
    )

    metrics_path = write_task_metrics(
        manager.get_run_dir(state.run_id),
        metrics,
    )

    return CheckpointedTaskResult(
        execution=result,
        commit=commit,
        metrics_path=metrics_path,
        security_review=security_review,
        optimization_review=optimization_review,
    )
