import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.services.plan_runner import run_execution_plan


def make_checkpoint(passed: bool, commit: str | None):
    execution = MagicMock()
    execution.passed = passed

    result = MagicMock()
    result.execution = execution
    result.commit = commit

    return result


@pytest.fixture(autouse=True)
def init_git_workspace(tmp_path):
    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )

    (tmp_path / "README.md").write_text("test\n")

    subprocess.run(
        ["git", "add", "-A"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=tmp_path,
        check=True,
    )


def test_multi_task_plan_runs_sequentially(tmp_path):
    plan = ExecutionPlan(
        request="Build calculator",
        tasks=[
            PlanTask(description="Create calculator module"),
            PlanTask(description="Add subtract function"),
        ],
    )

    finalization = MagicMock(
        analytics_path=Path("analytics.json"),
        retrospective_path=Path("retrospective.md"),
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            side_effect=[
                make_checkpoint(True, "commit1"),
                make_checkpoint(True, "commit2"),
            ],
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=finalization,
        ),
    ):
        result = run_execution_plan(
            plan=plan,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
            analytics_dir=tmp_path / "analytics",
        )

    assert result.passed is True
    assert result.completed_tasks == 2
    assert result.total_tasks == 2
    assert result.commits == ["commit1", "commit2"]
    assert executor.call_count == 2


def test_plan_stops_after_failed_task(tmp_path):
    plan = ExecutionPlan(
        request="Build feature",
        tasks=[
            PlanTask(description="Task one"),
            PlanTask(description="Task two"),
            PlanTask(description="Task three"),
        ],
    )

    finalization = MagicMock(
        analytics_path=Path("analytics.json"),
        retrospective_path=Path("retrospective.md"),
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            side_effect=[
                make_checkpoint(True, "commit1"),
                make_checkpoint(False, None),
            ],
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=finalization,
        ),
    ):
        result = run_execution_plan(
            plan=plan,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
        )

    assert result.passed is False
    assert result.completed_tasks == 1
    assert executor.call_count == 2
