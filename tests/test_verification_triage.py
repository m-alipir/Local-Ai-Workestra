import subprocess
from unittest.mock import patch

import pytest

from local_agent_orchestrator.services.test_runner import CommandResult
from local_agent_orchestrator.services.verification_triage import (
    VerificationTriageError,
    compare_verification,
    establish_baseline,
    summarize_verification,
)


def passed_result() -> CommandResult:
    return CommandResult(True, 0, "1 passed\n", "")


def failed_result(*identities: str) -> CommandResult:
    stdout = "\n".join(f"FAILED {identity} - assertion" for identity in identities)
    return CommandResult(False, 1, stdout + "\n", "")


def summary(command, result):
    return summarize_verification(command, result)


def test_clean_baseline_and_clean_post_change_are_allowed():
    decision = compare_verification(
        summary(["pytest", "-q"], passed_result()),
        summary(["pytest", "-q"], passed_result()),
    )

    assert decision.allowed is True
    assert decision.classification == "passed"


def test_clean_baseline_and_new_failure_are_rejected():
    decision = compare_verification(
        summary(["pytest", "-q"], passed_result()),
        summary(["pytest", "-q"], failed_result("tests/test_new.py::test_new")),
    )

    assert decision.allowed is False
    assert decision.classification == "new_failures"
    assert decision.new_failure_identities == ("tests/test_new.py::test_new",)


def test_preexisting_failure_that_remains_is_allowed():
    baseline = summary(
        ["uv", "run", "pytest", "-q"],
        failed_result("tests/test_admin.py::test_scheduler"),
    )
    post_change = summary(
        ["uv", "run", "pytest", "-q"],
        failed_result("tests/test_admin.py::test_scheduler"),
    )

    decision = compare_verification(baseline, post_change)

    assert decision.allowed is True
    assert decision.classification == "preexisting_failures_only"


def test_preexisting_failure_plus_new_failure_is_rejected():
    baseline = summary(
        ["pytest"],
        failed_result("tests/test_admin.py::test_scheduler"),
    )
    post_change = summary(
        ["pytest"],
        failed_result(
            "tests/test_admin.py::test_scheduler",
            "tests/test_new.py::test_new",
        ),
    )

    decision = compare_verification(baseline, post_change)

    assert decision.allowed is False
    assert decision.new_failure_identities == ("tests/test_new.py::test_new",)


def test_different_failure_replaces_baseline_failure_and_is_rejected():
    decision = compare_verification(
        summary(["pytest"], failed_result("tests/test_admin.py::test_scheduler")),
        summary(["pytest"], failed_result("tests/test_other.py::test_other")),
    )

    assert decision.allowed is False
    assert decision.classification == "new_failures"


def test_preexisting_failure_disappearing_is_allowed():
    decision = compare_verification(
        summary(["pytest"], failed_result("tests/test_admin.py::test_scheduler")),
        summary(["pytest"], passed_result()),
    )

    assert decision.allowed is True
    assert decision.classification == "baseline_failures_disappeared"


def test_unparseable_verification_failure_fails_closed():
    result = CommandResult(False, 2, "INTERNAL ERROR: worker crashed\n", "")
    parsed = summary(["pytest", "-q"], result)

    assert parsed.interpretable is False
    decision = compare_verification(parsed, parsed)
    assert decision.allowed is False
    assert decision.classification == "baseline_uninterpretable"


def test_non_pytest_failure_is_not_assumed_preexisting():
    result = CommandResult(False, 1, "failure\n", "")
    parsed = summary(["make", "test"], result)

    assert parsed.interpretable is False
    assert compare_verification(parsed, parsed).allowed is False


def test_baseline_uses_exact_workspace_and_command(tmp_path):
    baseline = passed_result()

    with patch(
        "local_agent_orchestrator.services.verification_triage.run_tests",
        return_value=baseline,
    ) as baseline_runner:
        establish_baseline(tmp_path, ["uv", "run", "pytest", "-q"])

    baseline_runner.assert_called_once_with(
        tmp_path.resolve(),
        ["uv", "run", "pytest", "-q"],
        timeout=120,
    )


def _git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )


def test_baseline_mutation_is_rolled_back_and_fails_closed(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "initial")

    def mutating_tests(*args, **kwargs):
        source.write_text("value = 2\n", encoding="utf-8")
        return passed_result()

    with patch(
        "local_agent_orchestrator.services.verification_triage.run_tests",
        side_effect=mutating_tests,
    ):
        with pytest.raises(VerificationTriageError) as raised:
            establish_baseline(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "baseline_workspace_mutated"
    assert source.read_text(encoding="utf-8") == "value = 1\n"
