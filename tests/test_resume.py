import json
import subprocess
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.models.plan import (
    ExecutionPlan,
    PlanTask,
)
from local_agent_orchestrator.services.resume import (
    approve_waiting_task,
    resume_execution_plan,
)
from local_agent_orchestrator.services.run_state import (
    RunStateManager,
)


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
    (path / "README.md").write_text("test\n")
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


def prepare_waiting_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    runs = tmp_path / "runs"
    manager = RunStateManager(runs)

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

    state = manager.create_run(plan.request)
    state.agent_branch = "agent/test-run"

    subprocess.run(
        ["git", "switch", "-c", state.agent_branch],
        cwd=repo,
        check=True,
    )

    manager.save(state)

    task = manager.add_task(
        state,
        plan.tasks[0].description,
    )

    (manager.get_run_dir(state.run_id) / "plan.json").write_text(
        json.dumps(plan.model_dump(mode="json"))
    )

    manager.mark_waiting_for_approval(
        state,
        task.id,
    )

    return runs, state.run_id, task.id, repo


def test_approve_waiting_task(tmp_path):
    runs, run_id, task_id, repo = prepare_waiting_run(
        tmp_path
    )

    approved = approve_waiting_task(
        run_id,
        runs_dir=runs,
    )

    manager = RunStateManager(runs)
    state = manager.load(run_id)
    task = manager.get_task(
        state,
        task_id,
    )

    assert approved == task_id
    assert task.approval_granted is True


def test_resume_executes_approved_code_task(tmp_path):
    runs, run_id, task_id, repo = prepare_waiting_run(
        tmp_path
    )

    approve_waiting_task(
        run_id,
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
        ) as executor,
        patch(
            "local_agent_orchestrator.services.resume.finalize_run",
            return_value=finalization,
        ),
    ):
        result = resume_execution_plan(
            run_id=run_id,
            workspace_root=repo,
            test_command=["pytest", "-q"],
            runs_dir=runs,
        )

    assert result.passed is True
    assert result.completed_tasks == 1
    assert result.commits == ["abc123"]
    executor.assert_called_once()


def test_resume_does_not_auto_execute_deploy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    runs = tmp_path / "runs"
    manager = RunStateManager(runs)

    plan = ExecutionPlan(
        request="Deploy",
        tasks=[
            PlanTask(
                id="deploy",
                description="Deploy production",
                kind="deploy",
                requires_approval=True,
                risk="high",
            )
        ],
    )

    state = manager.create_run(plan.request)
    state.agent_branch = "agent/test-deploy"

    subprocess.run(
        ["git", "switch", "-c", state.agent_branch],
        cwd=repo,
        check=True,
    )

    manager.save(state)

    task = manager.add_task(
        state,
        plan.tasks[0].description,
    )

    (manager.get_run_dir(state.run_id) / "plan.json").write_text(
        json.dumps(plan.model_dump(mode="json"))
    )

    manager.mark_waiting_for_approval(
        state,
        task.id,
    )

    approve_waiting_task(
        state.run_id,
        runs_dir=runs,
    )

    with patch(
        "local_agent_orchestrator.services.resume.execute_checkpointed_task"
    ) as executor:
        result = resume_execution_plan(
            run_id=state.run_id,
            workspace_root=repo,
            test_command=["pytest", "-q"],
            runs_dir=runs,
        )

    assert result.waiting_for_approval is True
    executor.assert_not_called()


def test_resume_switches_back_to_recorded_agent_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    runs = tmp_path / "runs"
    manager = RunStateManager(runs)

    plan = ExecutionPlan(
        request="Resume branch test",
        tasks=[
            PlanTask(
                id="task",
                description="Change something",
                kind="code",
                requires_approval=True,
            )
        ],
    )

    state = manager.create_run(plan.request)

    subprocess.run(
        ["git", "switch", "-c", "agent/test-branch"],
        cwd=repo,
        check=True,
    )

    state.agent_branch = "agent/test-branch"
    manager.save(state)

    task = manager.add_task(
        state,
        plan.tasks[0].description,
    )

    (manager.get_run_dir(state.run_id) / "plan.json").write_text(
        json.dumps(plan.model_dump(mode="json"))
    )

    manager.mark_waiting_for_approval(
        state,
        task.id,
    )

    approve_waiting_task(
        state.run_id,
        runs_dir=runs,
    )

    subprocess.run(
        ["git", "switch", "-c", "other-branch"],
        cwd=repo,
        check=True,
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
        resume_execution_plan(
            run_id=state.run_id,
            workspace_root=repo,
            test_command=["pytest", "-q"],
            runs_dir=runs,
        )

    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert branch == "agent/test-branch"
