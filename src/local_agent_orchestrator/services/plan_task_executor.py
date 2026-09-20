from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.models.task import VerificationStatus
from local_agent_orchestrator.services.dependency_bootstrap import (
    VerificationBootstrapError,
    prepare_verification_environment,
)
from local_agent_orchestrator.services.security import run_security_review
from local_agent_orchestrator.services.test_runner import (
    CommandResult,
    run_tests,
)


@dataclass(frozen=True, slots=True)
class PlanTaskExecution:
    passed: bool
    result: CommandResult
    verification_status: VerificationStatus
    detail: str = ""


def execute_test_task(
    workspace_root: str | Path,
    test_command: list[str],
) -> PlanTaskExecution:
    try:
        prepare_verification_environment(workspace_root, test_command)
    except VerificationBootstrapError as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Verification bootstrap failed [{exc.code}]: {exc.detail}",
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail=result.stderr,
        )

    try:
        result = run_tests(workspace_root, test_command)
    except (OSError, subprocess.SubprocessError) as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Trusted verification could not run: {exc}",
        )

    return PlanTaskExecution(
        passed=result.passed,
        result=result,
        verification_status=(
            VerificationStatus.ENFORCED_TRUSTED_COMMAND
            if result.passed
            else VerificationStatus.FAILED
        ),
        detail=result.stderr.strip() or result.stdout.strip(),
    )


def execute_review_task(
    workspace_root: str | Path,
    task: str,
) -> PlanTaskExecution:
    """Run mandatory Git validation, then the existing safe security reviewer."""

    try:
        root = Path(workspace_root).resolve()
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD^"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        revision = (
            [parent.stdout.strip(), "HEAD"]
            if parent.returncode == 0 and parent.stdout.strip()
            else ["HEAD"]
        )
        process = subprocess.run(
            ["git", "diff", "--check", *revision],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Review command could not run: {exc}",
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail=result.stderr,
        )

    if process.returncode != 0:
        result = CommandResult(
            passed=False,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail="Mandatory Git diff validation failed.",
        )

    try:
        changed_files_process = subprocess.run(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "HEAD",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Could not identify the committed files for review: {exc}",
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail=result.stderr,
        )
    if changed_files_process.returncode != 0:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout=changed_files_process.stdout,
            stderr="Could not identify the committed files for review.",
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail=result.stderr,
        )

    changed_files = [
        line.strip()
        for line in changed_files_process.stdout.splitlines()
        if line.strip()
    ]

    if not changed_files:
        result = CommandResult(
            passed=True,
            returncode=0,
            stdout="git diff --check passed; no committed files to review",
            stderr="",
        )
        return PlanTaskExecution(
            passed=True,
            result=result,
            verification_status=VerificationStatus.ENFORCED_TRUSTED_COMMAND,
            detail=result.stdout,
        )

    try:
        review = run_security_review(
            task=task,
            changed_files=changed_files,
            workspace_root=root,
            revision="HEAD",
        )
    except Exception as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Model review failed after Git validation: {exc}",
        )
        return PlanTaskExecution(
            passed=False,
            result=result,
            verification_status=VerificationStatus.FAILED,
            detail=result.stderr,
        )

    findings = "; ".join(
        f"[{finding.severity}] {finding.title}: {finding.description}"
        for finding in review.findings
    )
    blocking = review.has_blocking_findings
    result = CommandResult(
        passed=not blocking,
        returncode=1 if blocking else 0,
        stdout=findings or "Model review found no findings.",
        stderr="",
    )
    return PlanTaskExecution(
        passed=not blocking,
        result=result,
        verification_status=(
            VerificationStatus.ENFORCED_TRUSTED_COMMAND
            if not blocking
            else VerificationStatus.FAILED
        ),
        detail=result.stdout,
    )
