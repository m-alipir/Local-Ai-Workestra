from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.core.config import load_settings
from local_agent_orchestrator.services.checkpointed_executor import (
    CheckpointedTaskResult,
    execute_checkpointed_task,
)
from local_agent_orchestrator.services.finalizer import (
    FinalizationResult,
    finalize_run,
)
from local_agent_orchestrator.services.run_state import RunStateManager


@dataclass(slots=True)
class OrchestratorRunResult:
    run_id: str
    passed: bool
    attempts: int
    commit: str | None
    run_dir: Path
    metrics_path: Path
    analytics_path: Path
    retrospective_path: Path


def run_single_task(
    task: str,
    workspace_root: str | Path,
    test_command: list[str],
    runs_dir: str | Path | None = None,
    analytics_dir: str | Path = ".agent/analytics",
) -> OrchestratorRunResult:
    settings = load_settings()

    manager = RunStateManager(
        runs_dir or settings.paths.runs
    )

    state = manager.create_run(task)
    task_state = manager.add_task(
        state,
        task,
    )

    result: CheckpointedTaskResult = execute_checkpointed_task(
        state=state,
        manager=manager,
        task_id=task_state.id,
        task_description=task_state.description,
        workspace_root=workspace_root,
        test_command=test_command,
        retry_limit=settings.orchestrator.task_retry_limit,
    )

    run_dir = manager.get_run_dir(state.run_id)

    finalization: FinalizationResult = finalize_run(
        run_id=state.run_id,
        run_dir=run_dir,
        analytics_dir=analytics_dir,
    )

    return OrchestratorRunResult(
        run_id=state.run_id,
        passed=result.execution.passed,
        attempts=result.execution.attempts,
        commit=result.commit,
        run_dir=run_dir,
        metrics_path=result.metrics_path,
        analytics_path=finalization.analytics_path,
        retrospective_path=finalization.retrospective_path,
    )
