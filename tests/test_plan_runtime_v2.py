import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.models.security import SecurityFinding, SecurityReview
from local_agent_orchestrator.models.task import TaskStatus, VerificationStatus
from local_agent_orchestrator.services.plan_runner import (
    PlanExecutionError,
    run_execution_plan,
)
from local_agent_orchestrator.services.plan_task_executor import (
    PlanTaskExecution,
)
from local_agent_orchestrator.services.plan_validation import (
    PlanValidationError,
    validate_plan,
)
from local_agent_orchestrator.services.run_state import RunStateManager
from local_agent_orchestrator.services.test_runner import CommandResult
from local_agent_orchestrator.services.resume import resume_execution_plan


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
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
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=path,
        check=True,
    )


def _finalization():
    return MagicMock(analytics_path=None, retrospective_path=None)


def _checkpoint(passed: bool, commit: str | None = None):
    execution = MagicMock(passed=passed)
    return MagicMock(execution=execution, commit=commit)


def test_valid_dependency_chain_is_topologically_validated():
    plan = ExecutionPlan(
        request="chain",
        tasks=[
            PlanTask(id="a", description="A"),
            PlanTask(id="b", description="B", depends_on=["a"]),
            PlanTask(id="c", description="C", depends_on=["b"]),
        ],
    )

    validated = validate_plan(plan)

    assert validated.order == (0, 1, 2)


def test_reversed_input_is_executed_in_dependency_order(tmp_path):
    _init_repo(tmp_path)
    plan = ExecutionPlan(
        request="reverse",
        tasks=[
            PlanTask(id="b", description="B", depends_on=["a"]),
            PlanTask(id="a", description="A"),
        ],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            side_effect=[_checkpoint(True, "a"), _checkpoint(True, "b")],
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is True
    assert [call.kwargs["task_description"] for call in executor.call_args_list] == [
        "A",
        "B",
    ]


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        (
            [PlanTask(id="a", description="A", depends_on=["missing"])],
            "unknown task",
        ),
        (
            [PlanTask(id="a", description="A", depends_on=["a"])],
            "cannot depend on itself",
        ),
        (
            [
                PlanTask(id="a", description="A", depends_on=["b"]),
                PlanTask(id="b", description="B", depends_on=["a"]),
            ],
            "cycle",
        ),
    ],
)
def test_invalid_dependency_graph_fails_before_execution(tasks, message):
    with pytest.raises(PlanValidationError, match=message):
        validate_plan(ExecutionPlan(request="invalid", tasks=tasks))


def test_test_execution_rejects_test_creation_description():
    with pytest.raises(PlanValidationError, match="describes creating tests"):
        validate_plan(
            ExecutionPlan(
                request="invalid task kind",
                tasks=[
                    PlanTask(
                        id="tests",
                        description="Create automated tests",
                        kind="test",
                    )
                ],
            )
        )


def test_test_execution_requires_code_prerequisite():
    with pytest.raises(PlanValidationError, match="must depend on at least one code task"):
        validate_plan(
            ExecutionPlan(
                request="missing test prerequisite",
                tasks=[
                    PlanTask(id="implement", description="Implement the feature"),
                    PlanTask(id="verify", description="Run the trusted test suite", kind="test"),
                ],
            )
        )


def test_failed_dependency_blocks_dependent_task(tmp_path):
    _init_repo(tmp_path)
    plan = ExecutionPlan(
        request="blocked",
        tasks=[
            PlanTask(id="a", description="A"),
            PlanTask(id="b", description="B", depends_on=["a"]),
        ],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            return_value=_checkpoint(False),
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    state = RunStateManager(result.run_dir.parent).load(result.run_id)
    assert result.passed is False
    assert executor.call_count == 1
    assert [task.status for task in state.tasks] == [
        TaskStatus.FAILED,
        TaskStatus.BLOCKED,
    ]
    assert "a" in (state.tasks[1].error or "")


@pytest.mark.parametrize("risk", ["high", "critical"])
def test_high_risk_without_flag_still_waits_for_approval(tmp_path, risk):
    _init_repo(tmp_path)
    plan = ExecutionPlan(
        request="high risk",
        tasks=[
            PlanTask(
                id="sensitive",
                description="Sensitive change",
                risk=risk,
            )
        ],
    )

    result = run_execution_plan(
        plan,
        tmp_path,
        ["pytest", "-q"],
        runs_dir=tmp_path.parent / "runs",
    )

    state = RunStateManager(result.run_dir.parent).load(result.run_id)
    assert result.waiting_for_approval is True
    assert state.tasks[0].status == TaskStatus.WAITING_FOR_APPROVAL
    assert state.tasks[0].approval_granted is False
    assert (result.run_dir / "trajectory.jsonl").read_text().count(
        "approval_requested"
    ) == 1


def test_verification_metadata_is_informational_not_shell_execution(tmp_path):
    _init_repo(tmp_path)
    marker = tmp_path / "pwned"
    plan = ExecutionPlan(
        request="verify",
        tasks=[
            PlanTask(
                id="verify",
                description="Run tests",
                kind="test",
                verification=[f"$(touch {marker})"],
            )
        ],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_test_task",
            return_value=PlanTaskExecution(
                passed=True,
                result=CommandResult(True, 0, "ok", ""),
                verification_status=VerificationStatus.ENFORCED_TRUSTED_COMMAND,
            ),
        ) as verifier,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is True
    assert marker.exists() is False
    verifier.assert_called_once_with(tmp_path, ["pytest", "-q"])
    state = RunStateManager(result.run_dir.parent).load(result.run_id)
    assert state.tasks[0].verification == [f"$(touch {marker})"]


def test_code_verification_metadata_remains_informational(tmp_path):
    _init_repo(tmp_path)
    plan = ExecutionPlan(
        request="code",
        tasks=[
            PlanTask(
                id="code",
                description="Change code",
                verification=["the output is healthy"],
            )
        ],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            return_value=_checkpoint(True, "commit"),
        ),
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    state = RunStateManager(result.run_dir.parent).load(result.run_id)
    assert state.tasks[0].verification_status == VerificationStatus.INFORMATIONAL


def test_review_kind_uses_fixed_read_only_check(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "change"],
        cwd=tmp_path,
        check=True,
    )
    plan = ExecutionPlan(
        request="review",
        tasks=[PlanTask(id="review", description="Review diff", kind="review")],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_task_executor.run_security_review",
            return_value=SecurityReview(findings=[]),
        ) as reviewer,
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is True
    assert result.commits == []
    reviewer.assert_called_once()
    assert reviewer.call_args.kwargs["revision"] == "HEAD"


def test_blocking_model_review_fails_after_git_validation(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=tmp_path, check=True)
    plan = ExecutionPlan(
        request="review",
        tasks=[PlanTask(id="review", description="Review diff", kind="review")],
    )

    blocking = SecurityReview(findings=[SecurityFinding(
        severity="high",
        title="Unsafe change",
        description="The change is unsafe.",
        recommendation="Rework it.",
    )])
    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_task_executor.run_security_review",
            return_value=blocking,
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is False


def test_git_review_failure_prevents_model_review(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1 \n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "bad whitespace"], cwd=tmp_path, check=True)
    plan = ExecutionPlan(
        request="review",
        tasks=[PlanTask(id="review", description="Review diff", kind="review")],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_task_executor.run_security_review",
        ) as reviewer,
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is False
    reviewer.assert_not_called()


def test_model_review_failure_fails_closed_after_git_validation(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=tmp_path, check=True)
    plan = ExecutionPlan(
        request="review",
        tasks=[PlanTask(id="review", description="Review diff", kind="review")],
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=_finalization(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_task_executor.run_security_review",
            side_effect=RuntimeError("model unavailable"),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    assert result.passed is False


def test_unsupported_kind_fails_closed(tmp_path):
    _init_repo(tmp_path)
    task = PlanTask.model_construct(
        id="unknown",
        description="Unknown",
        kind="unknown",
        depends_on=[],
        verification=[],
        requires_approval=False,
        risk="low",
    )
    plan = ExecutionPlan.model_construct(request="unknown", tasks=[task])

    with pytest.raises(PlanExecutionError, match="unsupported"):
        run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )


def test_resume_skips_completed_dependency(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    runs = tmp_path / "runs"
    manager = RunStateManager(runs)
    state = manager.create_run("resume")
    state.agent_branch = "agent/resume"
    subprocess.run(["git", "switch", "-c", state.agent_branch], cwd=repo, check=True)
    manager.save(state)
    first = manager.add_task(state, "A")
    second = manager.add_task(state, "B")
    manager.update_task(state, first.id, TaskStatus.PASSED)
    (manager.get_run_dir(state.run_id) / "plan.json").write_text(
        ExecutionPlan(
            request="resume",
            tasks=[
                PlanTask(id="a", description="A"),
                PlanTask(id="b", description="B", depends_on=["a"]),
            ],
        ).model_dump_json()
    )

    with (
        patch(
            "local_agent_orchestrator.services.resume.execute_checkpointed_task",
            return_value=_checkpoint(True, "b"),
        ) as executor,
        patch(
            "local_agent_orchestrator.services.resume.finalize_run",
            return_value=_finalization(),
        ),
    ):
        result = resume_execution_plan(
            state.run_id,
            repo,
            ["pytest", "-q"],
            runs_dir=runs,
        )

    assert result.passed is True
    assert executor.call_count == 1
    assert executor.call_args.kwargs["task_description"] == "B"
