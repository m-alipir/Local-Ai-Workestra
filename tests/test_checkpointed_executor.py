import json
import subprocess
from unittest.mock import patch

from local_agent_orchestrator.models.security import SecurityReview
from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.git_workspace import GitWorkspaceError
from local_agent_orchestrator.services.checkpointed_executor import (
    execute_checkpointed_task,
)
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.task_executor import TaskExecutionResult
from local_agent_orchestrator.services.test_runner import CommandResult


def git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )


def make_repo(root):
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test User")

    (root / "app.py").write_text("x = 1\n")

    git(root, "add", "-A")
    git(root, "commit", "-m", "initial")


def make_result(passed):
    return TaskExecutionResult(
        passed=passed,
        attempts=1,
        changed_files=["app.py"],
        diagnoses=[],
        test_result=CommandResult(
            passed=passed,
            returncode=0 if passed else 1,
            stdout="passed" if passed else "failed",
            stderr="" if passed else "broken",
        ),
    )


def test_passed_task_creates_checkpoint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Build feature")
    task = manager.add_task(state, "Implement feature")
    execution = make_result(True)
    execution.accepted_model = "qwen_coder"
    execution.accepted_attempt = 2
    execution.operation_failures = [{
        "model": "qwen_coder",
        "attempt": 1,
        "failure_class": "no_match",
        "detail": "Exact replacement matched zero times: app.py",
    }]

    def fake_execute(**kwargs):
        (repo / "app.py").write_text("x = 2\n")
        return execution

    with patch(
        "local_agent_orchestrator.services.checkpointed_executor.execute_tracked_task",
        side_effect=fake_execute,
    ):
        result = execute_checkpointed_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=repo,
            test_command=["pytest", "-q"],
        )

    assert result.execution.passed is True
    assert result.commit is not None
    assert result.metrics_path.exists()

    content = git(
        repo,
        "show",
        "HEAD:app.py",
    ).stdout

    assert content == "x = 2\n"

    committed_files = git(
        repo,
        "diff",
        "--name-only",
        "HEAD^",
        "HEAD",
    ).stdout.splitlines()
    assert committed_files == result.execution.changed_files

    metrics = json.loads(result.metrics_path.read_text())
    assert metrics["passed"] is True
    assert metrics["commit"] == result.commit
    assert metrics["changed_files"] == result.execution.changed_files
    assert metrics["accepted_model"] == "qwen_coder"
    assert metrics["accepted_attempt"] == 2
    assert metrics["operation_failures"] == execution.operation_failures

    trajectory = (
        manager.get_run_dir(state.run_id) / "trajectory.jsonl"
    ).read_text().splitlines()
    checkpoint = [
        json.loads(line)
        for line in trajectory
        if json.loads(line)["event"] == "checkpoint_created"
    ][0]
    assert checkpoint["model"] == "qwen_coder"
    assert checkpoint["attempt"] == 2
    assert result.commit in checkpoint["detail"]


def test_checkpoint_failure_is_not_reported_as_success(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Build feature")
    task = manager.add_task(state, "Implement feature")

    def fake_execute(**kwargs):
        manager.update_task(state, task.id, TaskStatus.RUNNING)
        (repo / "app.py").write_text("x = 2\n")
        manager.update_task(state, task.id, TaskStatus.PASSED)
        return make_result(True)

    with (
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.execute_tracked_task",
            side_effect=fake_execute,
        ),
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.GitWorkspace.checkpoint",
            side_effect=GitWorkspaceError("commit hook failed"),
        ),
    ):
        result = execute_checkpointed_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=repo,
            test_command=["pytest", "-q"],
        )

    assert result.execution.passed is False
    assert result.commit is None
    assert result.execution.test_result.returncode == 125
    assert "commit hook failed" in result.execution.test_result.stderr
    assert manager.load(state.run_id).tasks[0].status == TaskStatus.FAILED
    assert manager.load(state.run_id).status == TaskStatus.FAILED
    assert repo.joinpath("app.py").read_text() == "x = 1\n"
    assert result.metrics_path.exists()
    metrics = json.loads(result.metrics_path.read_text())
    assert metrics["passed"] is False
    assert metrics["commit"] is None
    assert any(
        json.loads(line)["event"] == "checkpoint_failed"
        for line in (
            manager.get_run_dir(state.run_id) / "trajectory.jsonl"
        ).read_text().splitlines()
    )


def test_failed_task_rolls_back(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Build feature")
    task = manager.add_task(state, "Implement feature")

    def fake_execute(**kwargs):
        (repo / "app.py").write_text("broken\n")
        (repo / "temp.py").write_text("temporary\n")
        return make_result(False)

    with patch(
        "local_agent_orchestrator.services.checkpointed_executor.execute_tracked_task",
        side_effect=fake_execute,
    ):
        result = execute_checkpointed_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=repo,
            test_command=["pytest", "-q"],
        )

    assert result.execution.passed is False
    assert result.commit is None
    assert result.metrics_path.exists()
    assert (repo / "app.py").read_text() == "x = 1\n"
    assert not (repo / "temp.py").exists()


def test_security_review_runs_for_sensitive_task(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Add API authentication")
    task = manager.add_task(state, "Add API authentication")

    def fake_execute(**kwargs):
        (repo / "app.py").write_text("x = 2\n")
        return make_result(True)

    with (
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.execute_tracked_task",
            side_effect=fake_execute,
        ),
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.run_security_review",
            return_value=SecurityReview(findings=[]),
        ) as reviewer,
    ):
        result = execute_checkpointed_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=repo,
            test_command=["pytest", "-q"],
        )

    assert reviewer.call_count == 1
    assert result.security_review is not None
    assert result.security_review.findings == []


def test_optimizer_runs_for_performance_task(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    manager = RunStateManager(tmp_path / "runs")
    state = manager.create_run("Optimize database query latency")
    task = manager.add_task(state, "Optimize database query latency")

    def fake_execute(**kwargs):
        (repo / "app.py").write_text("x = 2\n")
        return make_result(True)

    with (
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.execute_tracked_task",
            side_effect=fake_execute,
        ),
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.requires_security_review",
            return_value=False,
        ),
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.requires_optimization_review",
            return_value=True,
        ),
        patch(
            "local_agent_orchestrator.services.checkpointed_executor.run_optimization_review",
            return_value="Measure before and after.",
        ) as optimizer,
    ):
        result = execute_checkpointed_task(
            state=state,
            manager=manager,
            task_id=task.id,
            task_description=task.description,
            workspace_root=repo,
            test_command=["pytest", "-q"],
        )

    assert optimizer.call_count == 1
    assert result.optimization_review == "Measure before and after."
