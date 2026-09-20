import json
import subprocess
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.services.plan_runner import run_execution_plan
from local_agent_orchestrator.services.resume import (
    approve_waiting_task,
    resume_execution_plan,
)
from local_agent_orchestrator.services.run_state import RunStateManager


def init_repo(path):
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
    )

    (path / "app.py").write_text(
        "def greet(name):\n"
        "    return f\"Hello {name}\"\n"
    )

    subprocess.run(
        ["git", "add", "-A"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=path,
        check=True,
    )


def test_approval_resume_restores_agent_branch_and_finishes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    runs = tmp_path / "runs"

    plan = ExecutionPlan(
        request="Sensitive code change",
        tasks=[
            PlanTask(
                id="change",
                description="Add farewell function",
                kind="code",
                requires_approval=True,
                risk="high",
            )
        ],
    )

    first = run_execution_plan(
        plan=plan,
        workspace_root=repo,
        test_command=["pytest", "-q"],
        runs_dir=runs,
    )

    assert first.waiting_for_approval is True
    assert first.waiting_task_id == "task-001"

    manager = RunStateManager(runs)
    state = manager.load(first.run_id)

    assert state.agent_branch is not None
    assert state.agent_branch.startswith("agent/")

    subprocess.run(
        ["git", "switch", state.base_branch],
        cwd=repo,
        check=True,
    )

    approve_waiting_task(
        first.run_id,
        runs_dir=runs,
    )

    execution = MagicMock(
        passed=True,
        attempts=1,
    )

    checkpoint = MagicMock(
        execution=execution,
        commit="abc123",
    )

    finalization = MagicMock(
        analytics_path=tmp_path / "analytics.json",
        retrospective_path=tmp_path / "retrospective.md",
    )

    with (
        patch(
            "local_agent_orchestrator.services.resume.execute_checkpointed_task",
            return_value=checkpoint,
        ),
        patch(
            "local_agent_orchestrator.services.resume.finalize_run",
            return_value=finalization,
        ),
    ):
        result = resume_execution_plan(
            run_id=first.run_id,
            workspace_root=repo,
            test_command=["pytest", "-q"],
            runs_dir=runs,
        )

    assert result.passed is True
    assert result.completed_tasks == 1

    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert current_branch == state.agent_branch

    resumed = manager.load(first.run_id)

    assert resumed.tasks[0].approval_granted is True
