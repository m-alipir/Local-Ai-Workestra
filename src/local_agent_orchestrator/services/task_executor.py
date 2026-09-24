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
from local_agent_orchestrator.models.scope import ScopeReview
from local_agent_orchestrator.services.scope_review import (
    review_unexpected_scope,
)
from local_agent_orchestrator.services.task_scope import (
    ScopeClassification,
    classify_changed_files,
)
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
MAX_SCOPE_REPAIRS = 2


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
    scope_reviews: list[dict[str, object]] = field(default_factory=list)


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


def _operation_retry_guidance(
    failure_class: str,
    detail: str = "",
) -> str:
    if failure_class == "whitespace_error":
        return (
            "\n\nWHITESPACE GUIDANCE: Regenerate only the affected create_file "
            "content with no trailing spaces or tabs on any line. Blank lines "
            "must contain no indentation. Preserve the requested file content "
            "and do not normalize existing-file replacements."
        )
    if failure_class == "invalid_schema":
        if "duplicate paths" in detail.lower():
            return (
                "\n\nDUPLICATE PATH REPAIR: The response had more than one "
                "operation for a file. Combine all changes to the same file "
                "into one operation. For an existing file, use one "
                "replace_exact operation with exact observed old_text spanning "
                "the required edits (including unchanged lines between them) "
                "and new_text containing every requested change. For a new "
                "file, use one create_file operation with complete content. "
                "Do not drop requested changes. Exact-match validation remains "
                "required; do not use fuzzy matching."
            )
        return (
            "\n\nSCHEMA REPAIR: Return one JSON object matching the semantic "
            "edit-operation schema exactly. Correct the reported validation "
            "error without weakening exact-match or path-safety requirements."
        )
    return ""


def _operation_failure_prompt(
    failure: dict[str, str | int],
) -> str:
    failure_class = str(failure["failure_class"])
    detail = _tail(str(failure["detail"]), MAX_RETRY_DIAGNOSIS_CHARS)
    return (
        "\n\nOPERATION_FAILURE_CLASS: "
        f"{failure_class}\n"
        "OPERATION_FAILURE_DETAIL: "
        f"{detail}\n"
        "Correct exactly this failure using the authoritative repository "
        "evidence above."
        + _operation_retry_guidance(failure_class, detail)
    )


def _current_changed_files(
    workspace_root: str | Path,
    fallback: list[str],
) -> list[str]:
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            check=False,
        )
        paths = list(dict.fromkeys(
            line.strip()
            for output in (diff.stdout, untracked.stdout)
            for line in output.splitlines()
            if line.strip()
        ))
        return paths or list(fallback)
    except OSError:
        return list(fallback)


def _scope_classification(
    changed_files: list[str],
    *,
    primary_scope: list[str],
    discouraged_scope: list[str],
    forbidden_scope: list[str],
    enabled: bool,
) -> ScopeClassification:
    if not enabled:
        return ScopeClassification(primary=tuple(changed_files))
    return classify_changed_files(
        changed_files,
        primary_scope=primary_scope,
        discouraged_scope=discouraged_scope,
        forbidden_scope=forbidden_scope,
    )


def _scope_guidance(
    primary_scope: list[str],
    discouraged_scope: list[str],
    forbidden_scope: list[str],
) -> str:
    return (
        "\n\nTASK SCOPE GUIDANCE:\n"
        "PRIMARY (expected changes):\n"
        + "\n".join(f"- {path}" for path in primary_scope)
        + "\nDISCOURAGED (allowed but requires focused review):\n"
        + "\n".join(f"- {path}" for path in discouraged_scope)
        + "\nFORBIDDEN (hard safety boundaries):\n"
        + "\n".join(f"- {path}" for path in forbidden_scope)
        + "\nPrimary scope guides the implementation; discouraged scope is not an "
        "automatic failure."
    )


def _scope_review_detail(review: ScopeReview) -> str:
    return (
        f"decision={review.decision}; reason={review.reason}; "
        f"preserve={','.join(review.preserve_paths)}; "
        f"remove={','.join(review.remove_paths)}; "
        f"instruction={review.instruction}"
    )


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
    primary_scope: list[str] | None = None,
    discouraged_scope: list[str] | None = None,
    forbidden_scope: list[str] | None = None,
    file_boundaries: list[str] | None = None,
) -> TaskExecutionResult:
    changed_files: list[str] = []
    last_result: CommandResult | None = None
    diagnoses: list[str] = []
    latest_repo_context: str | None = None
    operation_failures: list[dict[str, str | int]] = []
    scope_reviews: list[dict[str, object]] = []
    primary_scope = list(primary_scope or file_boundaries or [])
    discouraged_scope = list(discouraged_scope or [])
    forbidden_scope = list(forbidden_scope or [])
    scope_enabled = bool(
        primary_scope or discouraged_scope or forbidden_scope or file_boundaries
    )

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

    attempts_used = 0
    fresh_attempts_used = 0
    repair_attempts = 0
    repair_review: ScopeReview | None = None
    hard_scope_failure = False
    skip_diagnosis = False
    pending_schema_failure: dict[str, str | int] | None = None

    while fresh_attempts_used < qwen_attempts:
        attempts_used += 1
        attempt = attempts_used
        if repair_review is None:
            fresh_attempts_used += 1
        if event_callback:
            event_callback({
                "event": "model_attempt_started",
                "model": "qwen_coder",
                "attempt": attempt,
                "detail": "scope_repair" if repair_review else "fresh_attempt",
            })

        prompt = task
        if scope_enabled:
            prompt += _scope_guidance(
                primary_scope,
                discouraged_scope,
                forbidden_scope,
            )

        if repair_review is not None:
            prompt += (
                "\n\nREVISE THE CURRENT IMPLEMENTATION.\n"
                "Preserve correct implementation work and repair only the "
                "scope issue below.\n"
                f"PRESERVE PATHS: {', '.join(repair_review.preserve_paths) or '(none specified)'}\n"
                f"REMOVE OR REWORK PATHS: {', '.join(repair_review.remove_paths) or '(none specified)'}\n"
                f"REPAIR INSTRUCTION: {repair_review.instruction}\n"
                "Do not restart the implementation or make unrelated changes."
            )
        elif last_result is not None and not skip_diagnosis:
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

            if (
                operation_failures
                and operation_failures[-1].get("attempt") == attempt - 1
            ):
                prompt += _operation_failure_prompt(operation_failures[-1])

        elif skip_diagnosis:
            skip_diagnosis = False

        if pending_schema_failure is not None:
            prompt += _operation_failure_prompt(pending_schema_failure)
            pending_schema_failure = None

        try:
            coder_kwargs = {
                "coder": "qwen_coder",
                "context_callback": capture_context,
            }
            if forbidden_scope:
                coder_kwargs["forbidden_scope"] = forbidden_scope

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
            repair_review = None
            last_result = _coding_failure_result(exc)
            failure_class = _operation_failure_class(exc)
            failure = {
                "model": "qwen_coder",
                "attempt": attempt,
                "failure_class": failure_class,
                "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
            }
            operation_failures.append(failure)
            if failure_class == "invalid_schema":
                pending_schema_failure = failure
                skip_diagnosis = True

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

        changed_files = _current_changed_files(
            workspace_root,
            changed_files,
        )
        classification = _scope_classification(
            changed_files,
            primary_scope=primary_scope,
            discouraged_scope=discouraged_scope,
            forbidden_scope=forbidden_scope,
            enabled=scope_enabled,
        )
        if classification.forbidden:
            last_result = CommandResult(
                passed=False,
                returncode=125,
                stdout="",
                stderr=(
                    "Forbidden task scope change: "
                    + ", ".join(classification.forbidden)
                ),
            )
            operation_failures.append({
                "model": "qwen_coder",
                "attempt": attempt,
                "failure_class": "forbidden_scope",
                "detail": last_result.stderr,
            })
            hard_scope_failure = True
            repair_review = None
            if attempt_git is not None:
                attempt_git.rollback()
            if event_callback:
                event_callback({
                    "event": "scope_review",
                    "model": "qwen_coder",
                    "attempt": attempt,
                    "passed": False,
                    "scope_decision": "FAIL_HARD",
                    "scope_paths": list(classification.forbidden),
                    "detail": last_result.stderr,
                })
            break

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

        if not comparison.allowed:
            if attempt_git is not None:
                attempt_git.rollback()
            repair_review = None
            skip_diagnosis = False
            continue

        scope_review = ScopeReview(
            decision="PASS",
            reason="All changes are within the primary scope.",
            preserve_paths=list(changed_files),
        )
        if classification.grey:
            scope_review = review_unexpected_scope(
                task=task,
                workspace_root=workspace_root,
                changed_files=changed_files,
                primary_scope=primary_scope,
                discouraged_scope=discouraged_scope,
                forbidden_scope=forbidden_scope,
            )
            scope_reviews.append(scope_review.model_dump(mode="json"))
            if event_callback:
                event_callback({
                    "event": "scope_review",
                    "model": "gpt_oss",
                    "attempt": attempt,
                    "passed": scope_review.decision == "PASS",
                    "scope_decision": scope_review.decision,
                    "scope_paths": list(classification.grey),
                    "detail": _scope_review_detail(scope_review),
                })

        if scope_review.decision == "PASS":
            return TaskExecutionResult(
                passed=True,
                attempts=attempt,
                changed_files=changed_files,
                test_result=last_result,
                diagnoses=diagnoses,
                qwen_attempts=attempts_used,
                devstral_used=False,
                accepted_model="qwen_coder",
                accepted_attempt=attempt,
                baseline_result=baseline_result,
                baseline_failure_identities=baseline_failure_identities,
                post_change_failure_identities=post_change_failure_identities,
                verification_classification=verification_classification,
                operation_failures=operation_failures,
                scope_reviews=scope_reviews,
            )

        if (
            scope_review.decision == "REVISE"
            and repair_attempts < MAX_SCOPE_REPAIRS
        ):
            repair_attempts += 1
            repair_review = scope_review
            continue

        repair_review = None
        if scope_review.decision == "FAIL_HARD":
            hard_scope_failure = True
        if attempt_git is not None:
            attempt_git.rollback()
        skip_diagnosis = True

        if hard_scope_failure:
            break

    assert last_result is not None

    if repair_review is not None and attempt_git is not None:
        attempt_git.rollback()

    if hard_scope_failure:
        return TaskExecutionResult(
            passed=False,
            attempts=attempts_used,
            changed_files=[],
            test_result=last_result,
            diagnoses=diagnoses,
            qwen_attempts=attempts_used,
            devstral_used=False,
            baseline_result=baseline_result,
            baseline_failure_identities=baseline_failure_identities,
            post_change_failure_identities=post_change_failure_identities,
            verification_classification=verification_classification,
            operation_failures=operation_failures,
            scope_reviews=scope_reviews,
        )

    latest_failure = operation_failures[-1] if operation_failures else None
    schema_repair_required = bool(
        latest_failure
        and latest_failure["model"] == "qwen_coder"
        and latest_failure["failure_class"] == "invalid_schema"
    )
    if schema_repair_required:
        fallback_diagnosis = ""
    else:
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
        + (
            f"FINAL DIAGNOSIS:\n{_tail(fallback_diagnosis, MAX_RETRY_DIAGNOSIS_CHARS)}\n\n"
            if fallback_diagnosis
            else ""
        )
        + f"FAILURE STDOUT:\n{_tail(last_result.stdout, MAX_RETRY_OUTPUT_CHARS)}\n\n"
        + f"FAILURE STDERR:\n{_tail(last_result.stderr, MAX_RETRY_OUTPUT_CHARS)}\n\n"
        + "Produce the smallest correct fix using schema-valid semantic edit "
        + "operations. Do not make unrelated changes."
    )
    if scope_enabled:
        fallback_prompt += _scope_guidance(
            primary_scope,
            discouraged_scope,
            forbidden_scope,
        )

    if latest_failure:
        fallback_prompt += _operation_failure_prompt(latest_failure)

    if event_callback:
        event_callback({
            "event": "fallback_started",
            "model": "devstral",
            "attempt": attempts_used + 1,
        })

    try:
        fallback_kwargs = {
            "coder": "devstral",
            "context_callback": capture_context,
        }
        if forbidden_scope:
            fallback_kwargs["forbidden_scope"] = forbidden_scope

        if event_callback is not None:
            fallback_kwargs["operation_callback"] = (
                lambda operations: event_callback({
                    "event": "edit_operations_requested",
                    "model": "devstral",
                    "attempt": attempts_used + 1,
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
            "attempt": attempts_used + 1,
            "failure_class": failure_class,
            "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
        })

        if event_callback:
            event_callback({
                "event": "coding_output_rejected",
                "model": "devstral",
                "attempt": attempts_used + 1,
                "passed": False,
                "detail": _tail(str(exc), MAX_RETRY_DIAGNOSIS_CHARS),
                "failure_class": failure_class,
            })

        return TaskExecutionResult(
            passed=False,
            attempts=attempts_used + 1,
            changed_files=changed_files,
            test_result=last_result,
            diagnoses=diagnoses,
            qwen_attempts=attempts_used,
            devstral_used=True,
            accepted_model=None,
            accepted_attempt=None,
            baseline_result=baseline_result,
            baseline_failure_identities=baseline_failure_identities,
            post_change_failure_identities=post_change_failure_identities,
            verification_classification=verification_classification,
            operation_failures=operation_failures,
            scope_reviews=scope_reviews,
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
    changed_files = _current_changed_files(workspace_root, changed_files)
    classification = _scope_classification(
        changed_files,
        primary_scope=primary_scope,
        discouraged_scope=discouraged_scope,
        forbidden_scope=forbidden_scope,
        enabled=scope_enabled,
    )
    comparison_allowed = comparison.allowed
    comparison_detail = comparison.detail
    if classification.forbidden:
        comparison_allowed = False
        comparison_detail = (
            "Forbidden task scope change: "
            + ", ".join(classification.forbidden)
        )
        verification_classification = "forbidden_scope"
        operation_failures.append({
            "model": "devstral",
            "attempt": attempts_used + 1,
            "failure_class": "forbidden_scope",
            "detail": comparison_detail,
        })
    elif comparison_allowed and classification.grey:
        scope_review = review_unexpected_scope(
            task=task,
            workspace_root=workspace_root,
            changed_files=changed_files,
            primary_scope=primary_scope,
            discouraged_scope=discouraged_scope,
            forbidden_scope=forbidden_scope,
        )
        scope_reviews.append(scope_review.model_dump(mode="json"))
        if event_callback:
            event_callback({
                "event": "scope_review",
                "model": "gpt_oss",
                "attempt": attempts_used + 1,
                "passed": scope_review.decision == "PASS",
                "scope_decision": scope_review.decision,
                "scope_paths": list(classification.grey),
                "detail": _scope_review_detail(scope_review),
            })
        if scope_review.decision != "PASS":
            comparison_allowed = False
            comparison_detail = _scope_review_detail(scope_review)
            verification_classification = (
                f"scope_review_{scope_review.decision.lower()}"
            )

    if not comparison_allowed:
        operation_failures.append({
            "model": "devstral",
            "attempt": attempts_used + 1,
            "failure_class": "verification_failure",
            "detail": comparison_detail,
        })

    if event_callback:
        event_callback({
            "event": "tests_finished",
            "model": "devstral",
            "attempt": attempts_used + 1,
            "passed": last_result.passed,
            "detail": _test_detail(last_result),
            "verification_phase": "post_change",
            "failure_identities": post_change_failure_identities,
        })
        event_callback({
            "event": "verification_compared",
            "passed": comparison_allowed,
            "verification_phase": "comparison",
            "detail": comparison_detail,
            "failure_identities": post_change_failure_identities,
            "verification_classification": verification_classification,
            "failure_class": (
                None if comparison_allowed else "verification_failure"
            ),
        })

    if not comparison_allowed and attempt_git is not None:
        attempt_git.rollback()

    return TaskExecutionResult(
        passed=comparison_allowed,
        attempts=attempts_used + 1,
        changed_files=changed_files,
        test_result=last_result,
        diagnoses=diagnoses,
        qwen_attempts=attempts_used,
        devstral_used=True,
        accepted_model=("devstral" if comparison_allowed else None),
        accepted_attempt=(attempts_used + 1 if comparison_allowed else None),
        baseline_result=baseline_result,
        baseline_failure_identities=baseline_failure_identities,
        post_change_failure_identities=post_change_failure_identities,
        verification_classification=verification_classification,
        operation_failures=operation_failures,
        scope_reviews=scope_reviews,
    )
