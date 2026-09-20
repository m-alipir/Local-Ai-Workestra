from unittest.mock import patch

from local_agent_orchestrator.services.checkpointed_executor import (
    CheckpointedTaskResult,
)
from local_agent_orchestrator.services.finalizer import FinalizationResult
from local_agent_orchestrator.services.orchestrator import run_single_task
from local_agent_orchestrator.services.task_executor import (
    TaskExecutionResult,
)
from local_agent_orchestrator.services.test_runner import CommandResult


def test_run_single_task(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    metrics_path = tmp_path / "metrics.json"
    analytics_path = tmp_path / "analytics.json"
    retrospective_path = tmp_path / "retrospective.md"

    execution = TaskExecutionResult(
        passed=True,
        attempts=1,
        changed_files=["app.py"],
        test_result=CommandResult(
            passed=True,
            returncode=0,
            stdout="passed",
            stderr="",
        ),
        diagnoses=[],
    )

    checkpoint = CheckpointedTaskResult(
        execution=execution,
        commit="abc123",
        metrics_path=metrics_path,
        security_review=None,
        optimization_review=None,
    )

    finalization = FinalizationResult(
        analytics_path=analytics_path,
        retrospective_path=retrospective_path,
        task_count=1,
    )

    with (
        patch(
            "local_agent_orchestrator.services.orchestrator.execute_checkpointed_task",
            return_value=checkpoint,
        ) as executor,
        patch(
            "local_agent_orchestrator.services.orchestrator.finalize_run",
            return_value=finalization,
        ) as finalizer,
    ):
        result = run_single_task(
            task="Implement feature",
            workspace_root=repo,
            test_command=["pytest", "-q"],
            runs_dir=tmp_path / "runs",
            analytics_dir=tmp_path / "analytics",
        )

    assert result.passed is True
    assert result.attempts == 1
    assert result.commit == "abc123"
    assert result.run_dir.exists()

    executor.assert_called_once()
    finalizer.assert_called_once()
