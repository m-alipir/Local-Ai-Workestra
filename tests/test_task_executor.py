import subprocess
from unittest.mock import patch

from local_agent_orchestrator.services.dependency_bootstrap import (
    BootstrapResult,
    VerificationBootstrapError,
)
from local_agent_orchestrator.services.diff_patch import DiffPatchError
from local_agent_orchestrator.services.edit_operations import EditOperationError

from local_agent_orchestrator.services.task_executor import (
    execute_task_with_retries,
)
from local_agent_orchestrator.services.test_runner import CommandResult
from local_agent_orchestrator.services.verification_triage import (
    summarize_verification,
)


def baseline_passed():
    return summarize_verification(
        ["pytest", "-q"],
        CommandResult(True, 0, "1 passed\n", ""),
    )


def baseline_failed():
    return summarize_verification(
        ["pytest", "-q"],
        CommandResult(
            False,
            1,
            "FAILED tests/test_admin.py::test_scheduler - assertion\n",
            "",
        ),
    )


def init_repo(path):
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
    (path / "README.md").write_text("baseline\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=path,
        check=True,
    )


def test_bootstrap_failure_stops_before_coding_or_tests(tmp_path):
    events = []

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
            side_effect=VerificationBootstrapError(
                "bootstrap_failed",
                "trusted bootstrap exited with code 17",
            ),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
        ) as run,
    ):
        result = execute_task_with_retries(
            task="Implement feature",
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            event_callback=events.append,
        )

    assert result.passed is False
    assert result.attempts == 0
    assert result.qwen_attempts == 0
    assert result.test_result.returncode == 125
    assert "bootstrap_failed" in result.test_result.stderr
    assert coder.call_count == 0
    assert run.call_count == 0
    assert events == [{
        "event": "verification_bootstrap_failed",
        "passed": False,
        "detail": result.test_result.stderr,
    }]


def test_passes_first_attempt(tmp_path):
    good = CommandResult(
        passed=True,
        returncode=0,
        stdout="ok",
        stderr="",
    )

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=good,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="diagnosis",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is True
    assert result.attempts == 1
    assert coder.call_count == 1


def test_reused_bootstrap_is_recorded_for_retrospective(tmp_path):
    events = []

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
            return_value=BootstrapResult(status="reused"),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=CommandResult(True, 0, "ok", ""),
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            event_callback=events.append,
        )

    assert result.passed is True
    bootstrap_events = [
        event for event in events
        if event["event"] == "verification_bootstrapped"
    ]
    assert bootstrap_events == [{
        "event": "verification_bootstrapped",
        "passed": True,
        "detail": "status=reused",
    }]


def test_post_verification_spawn_failure_fails_closed(tmp_path):
    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=FileNotFoundError("pytest"),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="verification unavailable",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=0,
        )

    assert result.passed is False
    assert result.test_result.returncode == 125
    assert result.verification_classification == "post_change_uninterpretable"


def test_failed_attempt_edits_are_rolled_back_before_retry(tmp_path):
    init_repo(tmp_path)
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="FAILED tests/test_feature.py::test_feature - assertion\n",
        stderr="",
    )
    passed = CommandResult(True, 0, "1 passed\n", "")
    calls = []

    def fake_coder(*args, **kwargs):
        if not calls:
            (tmp_path / "failed.py").write_text("leak\n")
        else:
            (tmp_path / "accepted.py").write_text("kept\n")
        calls.append(True)
        return ["failed.py" if len(calls) == 1 else "accepted.py"]

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            side_effect=fake_coder,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=[failed, passed],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="retry",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=1,
        )

    assert result.passed is True
    assert result.accepted_model == "qwen_coder"
    assert result.accepted_attempt == 2
    assert not (tmp_path / "failed.py").exists()
    assert (tmp_path / "accepted.py").read_text() == "kept\n"


def test_retries_after_failure(tmp_path):
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="failed",
        stderr="assertion error",
    )

    good = CommandResult(
        passed=True,
        returncode=0,
        stdout="passed",
        stderr="",
    )

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=[failed, good],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="Fix the comparison logic.",
        ) as reviewer,
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is True
    assert result.attempts == 2
    assert coder.call_count == 2

    second_prompt = coder.call_args_list[1].args[0]

    assert "Previous implementation failed" in second_prompt
    assert "assertion error" in second_prompt
    assert "Fix the comparison logic." in second_prompt
    assert reviewer.call_count == 1
    assert result.diagnoses == ["Fix the comparison logic."]


def test_stops_after_retry_limit(tmp_path):
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="failed",
        stderr="still broken",
    )

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=failed,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="Still broken diagnosis",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is False
    assert result.attempts == 4
    assert coder.call_count == 4


def test_uses_devstral_after_qwen_retry_budget_is_exhausted(tmp_path):
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="failed",
        stderr="boom",
    )

    passed = CommandResult(
        passed=True,
        returncode=0,
        stdout="ok",
        stderr="",
    )

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=[
                failed,
                failed,
                failed,
                passed,
            ],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="fix it",
        ),
    ):
        result = execute_task_with_retries(
            task="Implement feature",
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is True
    assert result.attempts == 4

    assert coder.call_args_list[-1].kwargs[
        "coder"
    ] == "devstral"

    assert [
        call.kwargs["coder"]
        for call in coder.call_args_list
    ] == [
        "qwen_coder",
        "qwen_coder",
        "qwen_coder",
        "devstral",
    ]


def test_failure_diagnosis_receives_repo_context(tmp_path):
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="",
        stderr="failed",
    )

    passed = CommandResult(
        passed=True,
        returncode=0,
        stdout="ok",
        stderr="",
    )

    def fake_coder(
        task,
        workspace_root,
        *,
        coder="qwen_coder",
        context_callback=None,
    ):
        if context_callback:
            context_callback(
                "OBSERVED: app/existing_utils.py exists"
            )

        return ["app/existing_utils.py"]

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            side_effect=fake_coder,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=[
                failed,
                passed,
            ],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="Use observed utility module.",
        ) as reviewer,
    ):
        result = execute_task_with_retries(
            task="Implement helper",
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is True

    assert reviewer.call_args.kwargs[
        "repo_context"
    ] == "OBSERVED: app/existing_utils.py exists"


def test_retry_prompt_caps_failure_diagnostics(tmp_path):
    failed = CommandResult(
        passed=False,
        returncode=1,
        stdout="o" * 10_000,
        stderr="e" * 10_000,
    )
    passed = CommandResult(
        passed=True,
        returncode=0,
        stdout="ok",
        stderr="",
    )

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            side_effect=[failed, passed],
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="d" * 10_000,
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=2,
        )

    assert result.passed is True
    second_prompt = coder.call_args_list[1].args[0]
    assert len(second_prompt) < 7_000
    assert "...[truncated]" in second_prompt


def test_operation_failure_class_is_recorded_and_repeated_in_retry_prompt(tmp_path):
    passed = CommandResult(True, 0, "ok", "")
    prompts = []

    def fake_coder(task, workspace_root, **kwargs):
        prompts.append(task)
        if len(prompts) == 1:
            raise EditOperationError(
                "Exact replacement matched zero times: app.py",
                failure_class="no_match",
            )
        return ["app.py"]

    events = []
    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            side_effect=fake_coder,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=passed,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="retry",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=1,
            event_callback=events.append,
        )

    assert result.passed is True
    assert result.operation_failures == [{
        "model": "qwen_coder",
        "attempt": 1,
        "failure_class": "no_match",
        "detail": "Exact replacement matched zero times: app.py",
    }]
    rejected = [
        event for event in events
        if event["event"] == "coding_output_rejected"
    ]
    assert rejected[0]["failure_class"] == "no_match"
    assert len(rejected[0]["detail"]) <= 2_000
    assert "OPERATION_FAILURE_CLASS: no_match" in prompts[1]


def test_whitespace_failure_gets_precise_class_and_retry_guidance(tmp_path):
    passed = CommandResult(True, 0, "ok", "")
    prompts = []

    def fake_coder(task, workspace_root, **kwargs):
        prompts.append(task)
        if len(prompts) == 1:
            raise DiffPatchError("error: trailing whitespace.")
        return ["app.py"]

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            side_effect=fake_coder,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=passed,
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_passed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.diagnose_failure",
            return_value="retry",
        ),
    ):
        result = execute_task_with_retries(
            "Implement feature",
            tmp_path,
            ["pytest", "-q"],
            retry_limit=1,
        )

    assert result.passed is True
    assert result.operation_failures[0]["failure_class"] == "whitespace_error"
    assert "WHITESPACE GUIDANCE" in prompts[1]


def test_preexisting_failure_allows_checkpointable_task_result(tmp_path):
    existing_failure = CommandResult(
        passed=False,
        returncode=1,
        stdout="FAILED tests/test_admin.py::test_scheduler - assertion\n",
        stderr="",
    )
    events = []

    with (
        patch(
            "local_agent_orchestrator.services.task_executor.prepare_verification_environment",
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.establish_baseline",
            return_value=baseline_failed(),
        ),
        patch(
            "local_agent_orchestrator.services.task_executor.execute_coding_task",
            return_value=["app.py"],
        ) as coder,
        patch(
            "local_agent_orchestrator.services.task_executor.run_tests",
            return_value=existing_failure,
        ) as run,
    ):
        result = execute_task_with_retries(
            task="Implement feature",
            workspace_root=tmp_path,
            test_command=["pytest", "-q"],
            event_callback=events.append,
        )

    assert result.passed is True
    assert result.attempts == 1
    assert result.verification_classification == "preexisting_failures_only"
    assert result.baseline_failure_identities == [
        "tests/test_admin.py::test_scheduler"
    ]
    assert result.post_change_failure_identities == [
        "tests/test_admin.py::test_scheduler"
    ]
    assert coder.call_count == 1
    assert run.call_count == 1
    comparison = [
        event for event in events if event["event"] == "verification_compared"
    ]
    assert comparison[0]["passed"] is True
