from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from local_agent_orchestrator.services.git_workspace import (
    GitWorkspace,
    GitWorkspaceError,
)
from local_agent_orchestrator.services.test_runner import (
    CommandResult,
    run_tests,
)


_PYTHON_NAMES = {"python", "python3", "python.exe", "python3.exe"}
_PYTEST_FAILURE = re.compile(
    r"^\s*(?:FAILED|ERROR)\s+([^\s]+\.py(?:::[^\s]+)?)\s*(?:-|$)",
    re.MULTILINE,
)
_PYTEST_NO_TESTS = re.compile(
    r"^\s*no tests ran in \d+(?:\.\d+)?s\s*$",
    re.MULTILINE,
)
_PYTEST_NO_TESTS_IDENTITY = "pytest:no_tests_collected"


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    result: CommandResult
    failure_identities: tuple[str, ...]
    parser: str | None
    interpretable: bool
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationComparison:
    allowed: bool
    classification: str
    new_failure_identities: tuple[str, ...]
    detail: str


class VerificationTriageError(RuntimeError):
    """Baseline verification could not be established safely."""

    def __init__(
        self,
        code: str,
        detail: str,
        result: CommandResult | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.result = result
        super().__init__(detail)


def _verification_tool(command: Sequence[str]) -> str | None:
    if not command:
        return None

    tokens = list(command)
    first = Path(tokens[0]).name.lower()

    if first in {"uv", "uv.exe"}:
        if len(tokens) < 3 or tokens[1] != "run":
            return None
        tokens = tokens[2:]

    if (
        Path(tokens[0]).name.lower() in _PYTHON_NAMES
        and len(tokens) >= 3
        and tokens[1] == "-m"
    ):
        return Path(tokens[2]).name.lower()

    return Path(tokens[0]).name.lower()


def _is_pytest_command(command: Sequence[str]) -> bool:
    return _verification_tool(command) == "pytest"


def _parse_pytest_failures(result: CommandResult) -> tuple[str, ...]:
    text = f"{result.stdout}\n{result.stderr}"
    identities = set(_PYTEST_FAILURE.findall(text))
    # Pytest's exit code 5 is meaningful only with its canonical no-tests
    # summary. Do not treat arbitrary code 5 or empty output as interpretable.
    if result.returncode == 5 and _PYTEST_NO_TESTS.search(text):
        identities.add(_PYTEST_NO_TESTS_IDENTITY)
    return tuple(sorted(identities))


def summarize_verification(
    command: Sequence[str],
    result: CommandResult,
) -> VerificationSummary:
    if result.passed:
        parser = "pytest" if _is_pytest_command(command) else None
        return VerificationSummary(
            result=result,
            failure_identities=(),
            parser=parser,
            interpretable=True,
            detail="verification passed",
        )

    if not _is_pytest_command(command):
        return VerificationSummary(
            result=result,
            failure_identities=(),
            parser=None,
            interpretable=False,
            detail="non-zero verification has no supported failure parser",
        )

    identities = _parse_pytest_failures(result)
    if not identities:
        return VerificationSummary(
            result=result,
            failure_identities=(),
            parser="pytest",
            interpretable=False,
            detail="pytest failure identities were not found",
        )

    return VerificationSummary(
        result=result,
        failure_identities=identities,
        parser="pytest",
        interpretable=True,
        detail="pytest failure identities parsed",
    )


def compare_verification(
    baseline: VerificationSummary,
    post_change: VerificationSummary,
) -> VerificationComparison:
    if not baseline.interpretable:
        return VerificationComparison(
            allowed=False,
            classification="baseline_uninterpretable",
            new_failure_identities=(),
            detail=baseline.detail,
        )

    if not post_change.interpretable:
        return VerificationComparison(
            allowed=False,
            classification="post_change_uninterpretable",
            new_failure_identities=(),
            detail=post_change.detail,
        )

    if post_change.result.passed:
        classification = (
            "passed"
            if baseline.result.passed
            else "baseline_failures_disappeared"
        )
        return VerificationComparison(
            allowed=True,
            classification=classification,
            new_failure_identities=(),
            detail="post-change verification passed",
        )

    if baseline.result.passed:
        new_failures = post_change.failure_identities
        return VerificationComparison(
            allowed=False,
            classification="new_failures",
            new_failure_identities=new_failures,
            detail="post-change failures were absent from the clean baseline",
        )

    new_failures = tuple(
        sorted(
            set(post_change.failure_identities)
            - set(baseline.failure_identities)
        )
    )

    if new_failures:
        return VerificationComparison(
            allowed=False,
            classification="new_failures",
            new_failure_identities=new_failures,
            detail="post-change verification added failure identities",
        )

    return VerificationComparison(
        allowed=True,
        classification="preexisting_failures_only",
        new_failure_identities=(),
        detail="post-change failures are a subset of baseline failures",
    )


def _baseline_git_guard(
    workspace_root: Path,
) -> tuple[GitWorkspace, str] | None:
    git = GitWorkspace(workspace_root)

    try:
        git.assert_repository()
    except GitWorkspaceError:
        return None

    try:
        git.assert_clean()
        return git, git.head()
    except GitWorkspaceError as exc:
        raise VerificationTriageError(
            "baseline_workspace_dirty",
            str(exc),
        ) from exc


def establish_baseline(
    workspace_root: str | Path,
    command: Sequence[str],
    timeout: int = 120,
) -> VerificationSummary:
    root = Path(workspace_root).resolve()
    guard = _baseline_git_guard(root)

    try:
        result = run_tests(root, list(command), timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        result = CommandResult(
            passed=False,
            returncode=125,
            stdout="",
            stderr=f"Verification execution failed: {type(exc).__name__}: {exc}",
        )
        raise VerificationTriageError(
            "baseline_execution_failed",
            result.stderr,
            result=result,
        ) from exc

    if guard is not None:
        git, baseline_head = guard
        try:
            current_head = git.head()
            changed = git.status()
        except GitWorkspaceError as exc:
            raise VerificationTriageError(
                "baseline_workspace_unavailable",
                str(exc),
                result=result,
            ) from exc

        if current_head != baseline_head:
            raise VerificationTriageError(
                "baseline_changed_head",
                "baseline verification changed the target Git HEAD",
                result=result,
            )

        if changed:
            git.rollback()
            raise VerificationTriageError(
                "baseline_workspace_mutated",
                "baseline verification mutated the clean target workspace; it was rolled back",
                result=result,
            )

    summary = summarize_verification(command, result)

    if not summary.interpretable:
        raise VerificationTriageError(
            "baseline_uninterpretable",
            summary.detail,
            result=result,
        )

    return summary
