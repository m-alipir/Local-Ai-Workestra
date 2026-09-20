import subprocess
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    PlanTask,
)
from local_agent_orchestrator.services.plan_runner import (
    PlanExecutionError,
    run_execution_plan,
)
from local_agent_orchestrator.services.plan_task_executor import (
    PlanTaskExecution,
)
from local_agent_orchestrator.models.task import VerificationStatus
from local_agent_orchestrator.services.test_runner import CommandResult


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


def test_deploy_task_requires_human_approval(tmp_path):
    plan = ExecutionPlan(
        request="Deploy release",
        tasks=[
            PlanTask(
                id="deploy",
                description="Deploy production",
                kind="deploy",
                risk="high",
            )
        ],
    )

    result = run_execution_plan(
        plan=plan,
        workspace_root=tmp_path,
        test_command=["pytest", "-q"],
        runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
    )

    assert result.waiting_for_approval is True
    assert result.waiting_task_id == "task-001"
    assert result.passed is False


def test_explicit_approval_gate_blocks_code_task(tmp_path):
    plan = ExecutionPlan(
        request="Sensitive change",
        tasks=[
            PlanTask(
                id="sensitive",
                description="Change permissions",
                kind="code",
                requires_approval=True,
                risk="high",
            )
        ],
    )

    result = run_execution_plan(
        plan=plan,
        workspace_root=tmp_path,
        test_command=["pytest", "-q"],
        runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
    )

    assert result.waiting_for_approval is True
    assert result.waiting_task_id == "task-001"


def test_unknown_dependency_is_rejected(tmp_path):
    plan = ExecutionPlan(
        request="Feature",
        tasks=[
            PlanTask(
                id="task-b",
                description="Second task",
                depends_on=["missing"],
            )
        ],
    )

    with pytest.raises(
        PlanExecutionError,
        match="unknown task",
    ):
        run_execution_plan(
            plan=plan,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
        )


def test_test_kind_uses_explicit_trusted_executor(tmp_path):
    plan = ExecutionPlan(
        request="Verification",
        tasks=[
            PlanTask(
                id="verify",
                description="Run verification",
                kind="test",
            )
        ],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task"
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_test_task",
            return_value=PlanTaskExecution(
                passed=True,
                result=CommandResult(True, 0, "passed", ""),
                verification_status=VerificationStatus.ENFORCED_TRUSTED_COMMAND,
            ),
        ) as verifier,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=MagicMock(analytics_path=None, retrospective_path=None),
        ),
    ):
        result = run_execution_plan(
            plan=plan,
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            runs_dir=tmp_path.parent / (tmp_path.name + "-runs"),
        )

    assert result.passed is True
    verifier.assert_called_once()
    executor.assert_not_called()
