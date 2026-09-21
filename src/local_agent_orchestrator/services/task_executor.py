from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from local_agent_orchestrator.services.coding_executor import (
    execute_coding_task,
)
from local_agent_orchestrator.services.edit_operations import (
    EditOperationError,
)
from local_agent_orchestrator.services.dependency_bootstrap import (
    VerificationBootstrapError,
    prepare_verification_environment,
)
from local_agent_orchestrator.services.diff_patch import DiffPatchError
from local_agent_orchestrator.services.git_workspace import (
    GitWorkspace,
    GitWorkspaceError,
)
from local_agent_orchestrator.services.patches import PatchError
from local_agent_orchestrator.services.reviewer import diagnose_failure
from local_agent_orchestrator.services.test_runner import (
    CommandResult,
    run_tests,
)
from local_agent_orchestrator.services.verification_triage import (
    VerificationTriageError,
    compare_verification,
    establish_baseline,
    summarize_verification,
)


MAX_RETRY_DIAGNOSIS_CHARS = 2_000
MAX_RETRY_OUTPUT_CHARS = 2_000


@dataclass(slots=True)
class TaskExecutionResult:
    passed: bool
    attempts: int
    changed_files: list[str]
    test_result: CommandResult
    diagnoses: list[str]
    qwen_attempts: int = 0
    devstral_used: bool = False
    accepted_model: str | None = None
    accepted_attempt: int | None = None
    baseline_result: CommandResult | None = None
    baseline_failure_identities: list[str] = field(default_factory=list)
    post_change_failure_identities: list[str] = field(default_factory=list)
    verification_classification: str | None = None
    operation_failures: list[dict[str, str | int]] = field(
        default_factory=list,
    )


def _coding_failure_result(exc: Exception) -> CommandResult:
    return CommandResult(
        passed=False,
        returncode=1,
        stdout="",
        stderr=(
            "Coding output could not be safely applied: "
            f"{type(exc).__name__}: {exc}"
        ),
    )


def _operation_failure_class(exc: Exception) -> str:
    if isinstance(exc, EditOperationError):
        return exc.failure_class
    if isinstance(exc, (DiffPatchError, PatchError)):
        if "trailing whitespace" in str(exc).lower():
            return "whitespace_error"
        return "patch_validation_failure"
    if isinstance(exc, ValueError):
        return "invalid_schema"
    return "invalid_operation"


def _tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "...[truncated]\n" + text[-limit:]


def _operation_retry_guidance(failure_class: str) -> str:
    if failure_class == "whitespace_error":
        return (
            "\n\nWHITESPACE GUIDANCE: Regenerate only the affected create_file "
            "content with no trailing spaces or tabs on any line. Blank lines "
            "must contain no indentation. Preserve the requested file content "
            "and do not normalize existing-file replacements."
        )
    return ""


def _test_detail(result: CommandResult) -> str:
    return (
        f"returncode={result.returncode}\n"
        f"STDOUT:\n{_tail(result.stdout, MAX_RETRY_OUTPUT_CHARS)}\n"
        f"STDERR:\n{_tail(result.stderr, MAX_RETRY_OUTPUT_CHARS)}"
    )


def _run_post_verification(
    workspace_root: str | Path,
    test_command: list[str],
) -> CommandResult:
    try:
        return run_tests(workspace_root, test_command)
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=(
                "Verification execution failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        )


def _prepare_attempt_workspace(
    workspace_root: str | Path,
) -> GitWorkspace | None:
    git = GitWorkspace(workspace_root)

    try:
        git.assert_repository()
    except GitWorkspaceError:
        return None

    git.assert_clean()
    return git


def execute_task_with_retries(
    task: str,
    workspace_root: str | Path,
    test_command: list[str],
    retry_limit: int = 2,
    event_callback: Callable[[dict], None] | None = None,
) -> TaskExecutionResult:
    changed_files: list[str] = []
    last_result: CommandResult | None = None
    diagnoses: list[str] = []
    latest_repo_context: str | None = None
    operation_failures: list[dict[str, str | int]] = []

    def capture_context(context: str) -> None:
        nonlocal latest_repo_context
        latest_repo_context = context

    qwen_attempts = retry_limit + 1

    try:
        bootstrap = prepare_verification_environment(
            workspace_root,
            test_command,
        )
    except VerificationBootstrapError as exc:
        last_result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=(
                "Verification bootstrap failed "
                f"[{exc.code}]: {exc.detail}"
            ),
        )

        if event_callback:
            event_callback({
                "event": "verification_bootstrap_failed",
                "passed": False,
                "detail": last_result.stderr,
            })

        return TaskExecutionResult(
            passed=False,
            attempts=0,
            changed_files=[],
            test_result=last_result,
            diagnoses=[],
            qwen_attempts=0,
            devstral_used=False,
        )

    if event_callback and bootstrap.status in {"bootstrapped", "reused"}:
        event_callback({
            "event": "verification_bootstrapped",
            "passed": True,
            "detail": (
                f"status={bootstrap.status} "
                + " ".join(bootstrap.command or ())
            ).strip(),
        })

    attempt_git = _prepare_attempt_workspace(workspace_root)

    try:
        baseline = establish_baseline(
            workspace_root,
            test_command,
        )
    except VerificationTriageError as exc:
        baseline_result = exc.result or CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=exc.detail,
        )
        last_result = CommandResult(
            passed=False,
            returncode=125,
            stdout=baseline_result.stdout,
            stderr=(
                "Verification baseline failed "
                f"[{exc.code}]: {exc.detail}"
            ),
        )

        if event_callback:
            event_callback({
                "event": "verification_baseline_failed",
                "passed": False,
                "verification_phase": "baseline",
                "detail": _test_detail(baseline_result),
                "verification_classification": exc.code,
            })

        return TaskExecutionResult(
            passed=False,
            attempts=0,
            changed_files=[],
            test_result=last_result,
            diagnoses=[],
            qwen_attempts=0,
            devstral_used=False,
            baseline_result=baseline_result,
            verification_classification=exc.code,
        )

    baseline_result = baseline.result
    baseline_failure_identities = list(baseline.failure_identities)
    post_change_failure_identities: list[str] = []
    verification_classification: str | None = None

    if event_callback:
        event_callback({
            "event": "verification_baseline_finished",
            "passed": baseline.result.passed,
            "verification_phase": "baseline",
            "detail": _test_detail(baseline.result),
            "failure_identities": baseline_failure_identities,
            "verification_classification": (
                "baseline_passed"
                if baseline.result.passed
                else "baseline_failures_identified"
            ),
        })

    for attempt in range(1, qwen_attempts + 1):
        if event_callback:
            event_callback({
                "event": "model_attempt_started",
                "model": "qwen_coder",
                "attempt": attempt,
            })

        prompt = task

        if last_result is not None:
            diagnosis = diagnose_failure(
                task=task,
                stdout=last_result.stdout,
                stderr=last_result.stderr,
                repo_context=latest_repo_context,
            )
            diagnoses.append(diagnosis)

            prompt += (
                "\n\nPrevious implementation failed.\n"
                "A debugging reviewer analyzed the failure.\n\n"
                f"DIAGNOSIS:\n{_tail(diagnosis, MAX_RETRY_DIAGNOSIS_CHARS)}\n\n"
                f"FAILURE STDOUT:\n{_tail(last_result.stdout, MAX_RETRY_OUTPUT_CHARS)}\n\n"
                f"FAILURE STDERR:\n{_tail(last_result.stderr, MAX_RETRY_OUTPUT_CHARS)}\n\n"
                "Produce a corrected implementation. "
                "Return schema-valid semantic edit operations. "
                "Use exact observed text for replacements and do not guess paths. "
                "Do not make unrelated changes."
            )

            if operation_failures:
                failure = operation_failures[-1]
                prompt += (
                    "\n\nOPERATION_FAILURE_CLASS: "
                    f"{failure['failure_class']}\n"
                    "OPERATION_FAILURE_DETAIL: "
                    f"{failure['detail']}\n"
                    "Correct exactly this failure using the authoritative "
                    "repository evidence above."
                    + _operation_retry_guidance(failure["failure_class"])
                )

        try:
            coder_kwargs = {
                "coder": "qwen_coder",
                "context_callback": capture_context,
            }

            if event_callback is not None:
                coder_kwargs["operation_callback"] = (
                    lambda operations: event_callback({
                        "event": "edit_operations_requested",
                        "model": "qwen_coder",
                        "attempt": attempt,
                        "operations": operations,
                    })
                )

            changed_files = execute_coding_task(
                prompt,
                workspace_root,
                **coder_kwargs,
            )
        except (DiffPatchError, PatchError, ValueError) as exc:
            if attempt_git is not None:
                attempt_git.rollback()
            last_result = _coding_failure_result(exc)
            failure_class = _operation_failure_class(exc)
            operation_failures.append({
                "model": "qwen_coder",
                "attempt": attempt,
                "failure_class": failure_class,
                "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
            })

            if event_callback:
                event_callback({
                    "event": "coding_output_rejected",
                    "model": "qwen_coder",
                    "attempt": attempt,
                    "passed": False,
                    "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
                    "failure_class": failure_class,
                })

            continue

        last_result = _run_post_verification(
            workspace_root,
            test_command,
        )

        post_change = summarize_verification(
            test_command,
            last_result,
        )
        comparison = compare_verification(
            baseline,
            post_change,
        )
        post_change_failure_identities = list(
            post_change.failure_identities
        )
        verification_classification = comparison.classification

        if not comparison.allowed:
            operation_failures.append({
                "model": "qwen_coder",
                "attempt": attempt,
                "failure_class": "verification_failure",
                "detail": comparison.classification,
            })

        if event_callback:
            event_callback({
                "event": "tests_finished",
                "model": "qwen_coder",
                "attempt": attempt,
                "passed": last_result.passed,
                "detail": _test_detail(last_result),
                "verification_phase": "post_change",
                "failure_identities": post_change_failure_identities,
            })
            event_callback({
                "event": "verification_compared",
                "passed": comparison.allowed,
                "verification_phase": "comparison",
                "detail": comparison.detail,
                "failure_identities": post_change_failure_identities,
                "verification_classification": comparison.classification,
                "failure_class": (
                    None if comparison.allowed else "verification_failure"
                ),
            })

        if comparison.allowed:
            return TaskExecutionResult(
                passed=True,
                attempts=attempt,
                changed_files=changed_files,
                test_result=last_result,
                diagnoses=diagnoses,
                qwen_attempts=attempt,
                devstral_used=False,
                accepted_model="qwen_coder",
                accepted_attempt=attempt,
                baseline_result=baseline_result,
                baseline_failure_identities=baseline_failure_identities,
                post_change_failure_identities=post_change_failure_identities,
                verification_classification=verification_classification,
                operation_failures=operation_failures,
            )

        if attempt_git is not None:
            attempt_git.rollback()

    assert last_result is not None

    fallback_diagnosis = diagnose_failure(
        task=task,
        stdout=last_result.stdout,
        stderr=last_result.stderr,
    )
    diagnoses.append(fallback_diagnosis)

    fallback_prompt = (
        task
        + "\n\n"
        + "The primary coding agent exhausted its retry budget.\n"
        + "You are the fallback engineer.\n\n"
        + f"FINAL DIAGNOSIS:\n{_tail(fallback_diagnosis, MAX_RETRY_DIAGNOSIS_CHARS)}\n\n"
        + f"FAILURE STDOUT:\n{_tail(last_result.stdout, MAX_RETRY_OUTPUT_CHARS)}\n\n"
        + f"FAILURE STDERR:\n{_tail(last_result.stderr, MAX_RETRY_OUTPUT_CHARS)}\n\n"
        + "Produce the smallest correct fix using schema-valid semantic edit "
        + "operations. Do not make unrelated changes."
    )

    if operation_failures:
        failure = operation_failures[-1]
        fallback_prompt += (
            "\n\nOPERATION_FAILURE_CLASS: "
            f"{failure['failure_class']}\n"
            "OPERATION_FAILURE_DETAIL: "
            f"{failure['detail']}\n"
            "Correct exactly this failure using the authoritative repository "
            "evidence supplied to your coder context."
            + _operation_retry_guidance(failure["failure_class"])
        )

    if event_callback:
        event_callback({
            "event": "fallback_started",
            "model": "devstral",
            "attempt": qwen_attempts + 1,
        })

    try:
        fallback_kwargs = {
            "coder": "devstral",
            "context_callback": capture_context,
        }

        if event_callback is not None:
            fallback_kwargs["operation_callback"] = (
                lambda operations: event_callback({
                    "event": "edit_operations_requested",
                    "model": "devstral",
                    "attempt": qwen_attempts + 1,
                    "operations": operations,
                })
            )

        changed_files = execute_coding_task(
            fallback_prompt,
            workspace_root,
            **fallback_kwargs,
        )
    except (DiffPatchError, PatchError, ValueError) as exc:
        if attempt_git is not None:
            attempt_git.rollback()
        last_result = _coding_failure_result(exc)
        failure_class = _operation_failure_class(exc)
        operation_failures.append({
            "model": "devstral",
            "attempt": qwen_attempts + 1,
            "failure_class": failure_class,
            "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
        })

        if event_callback:
            event_callback({
                "event": "coding_output_rejected",
                "model": "devstral",
                "attempt": qwen_attempts + 1,
                "passed": False,
                "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
                "failure_class": failure_class,
            })

        return TaskExecutionResult(
            passed=False,
            attempts=qwen_attempts + 1,
            changed_files=changed_files,
            test_result=last_result,
            diagnoses=diagnoses,
            qwen_attempts=qwen_attempts,
            devstral_used=True,
            accepted_model=None,
            accepted_attempt=None,
            baseline_result=baseline_result,
            baseline_failure_identities=baseline_failure_identities,
            post_change_failure_identities=post_change_failure_identities,
            verification_classification=verification_classification,
            operation_failures=operation_failures,
        )

    last_result = _run_post_verification(
        workspace_root,
        test_command,
    )

    post_change = summarize_verification(
        test_command,
        last_result,
    )
    comparison = compare_verification(
        baseline,
        post_change,
    )
    post_change_failure_identities = list(
        post_change.failure_identities
    )
    verification_classification = comparison.classification

    if not comparison.allowed:
        operation_failures.append({
            "model": "devstral",
            "attempt": qwen_attempts + 1,
            "failure_class": "verification_failure",
            "detail": comparison.classification,
        })

    if event_callback:
        event_callback({
            "event": "tests_finished",
            "model": "devstral",
            "attempt": qwen_attempts + 1,
            "passed": last_result.passed,
            "detail": _test_detail(last_result),
            "verification_phase": "post_change",
            "failure_identities": post_change_failure_identities,
        })
        event_callback({
            "event": "verification_compared",
            "passed": comparison.allowed,
            "verification_phase": "comparison",
            "detail": comparison.detail,
            "failure_identities": post_change_failure_identities,
            "verification_classification": comparison.classification,
            "failure_class": (
                None if comparison.allowed else "verification_failure"
            ),
        })

    if not comparison.allowed and attempt_git is not None:
        attempt_git.rollback()

    return TaskExecutionResult(
        passed=comparison.allowed,
        attempts=qwen_attempts + 1,
        changed_files=changed_files,
        test_result=last_result,
        diagnoses=diagnoses,
        qwen_attempts=qwen_attempts,
        devstral_used=True,
        accepted_model=("devstral" if comparison.allowed else None),
        accepted_attempt=(qwen_attempts + 1 if comparison.allowed else None),
        baseline_result=baseline_result,
        baseline_failure_identities=baseline_failure_identities,
        post_change_failure_identities=post_change_failure_identities,
        verification_classification=verification_classification,
        operation_failures=operation_failures,
    )
