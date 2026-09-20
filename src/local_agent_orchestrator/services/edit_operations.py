from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from local_agent_orchestrator.models.edit import EditOperationsResponse
from local_agent_orchestrator.services.patches import PatchError
from local_agent_orchestrator.services.workspace import (
    Workspace,
    WorkspaceError,
)


class EditOperationError(PatchError):
    def __init__(
        self,
        message: str,
        *,
        failure_class: str = "invalid_operation",
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class


def parse_edit_response(text: str) -> EditOperationsResponse:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    if not cleaned:
        raise EditOperationError(
            "Model response contains no JSON object.",
            failure_class="invalid_schema",
        )

    decoder = json.JSONDecoder()

    try:
        data, end = decoder.raw_decode(cleaned)
    except json.JSONDecodeError as exc:
        raise EditOperationError(
            f"Model returned invalid JSON: {exc}",
            failure_class="invalid_schema",
        ) from exc

    if cleaned[end:].strip():
        raise EditOperationError(
            "Model returned trailing text after the JSON object.",
            failure_class="invalid_schema",
        )

    try:
        return EditOperationsResponse.model_validate(data)
    except ValidationError as exc:
        detail = f"Model returned invalid edit-operation schema: {exc}"
        failure_class = (
            "empty_old_text"
            if "requires a non-empty old_text" in str(exc)
            and "create_file requires content" not in str(exc)
            else "invalid_schema"
        )
        raise EditOperationError(
            detail,
            failure_class=failure_class,
        ) from exc


def _run_git(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )

    if check and result.returncode != 0:
        raise EditOperationError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"git command failed: {' '.join(args)}",
            failure_class="patch_validation_failure",
        )

    return result


def _validate_path(workspace: Workspace, path: str) -> Path:
    candidate = Path(path)

    if candidate.is_absolute():
        raise EditOperationError(
            f"Absolute path is not allowed: {path}",
            failure_class="unsafe_path",
        )

    if ".." in candidate.parts:
        raise EditOperationError(
            f"Parent traversal is not allowed: {path}",
            failure_class="unsafe_path",
        )

    try:
        return workspace._resolve_safe(path)
    except WorkspaceError as exc:
        raise EditOperationError(
            str(exc),
            failure_class="unsafe_path",
        ) from exc


def _validate_operations(
    workspace: Workspace,
    response: EditOperationsResponse,
    grounded_paths: set[str],
) -> dict[str, str | None]:
    candidate_contents: dict[str, str | None] = {}
    seen_resolved_paths: set[Path] = set()

    for operation in response.operations:
        path = operation.path
        resolved = _validate_path(workspace, path)

        if resolved in seen_resolved_paths:
            raise EditOperationError(
                f"Multiple operations target the same path: {path}",
                failure_class="invalid_operation",
            )
        seen_resolved_paths.add(resolved)

        if operation.kind == "create_file":
            if resolved.exists():
                raise EditOperationError(
                    f"New file path already exists: {path}",
                    failure_class="path_conflict",
                )
            candidate_contents[path] = operation.content
            continue

        if path not in grounded_paths:
            raise EditOperationError(
                f"Edit path is not grounded in repository evidence: {path}",
                failure_class="ungrounded_path",
            )

        if not resolved.exists():
            raise EditOperationError(
                f"Existing edit path does not exist: {path}",
                failure_class="ungrounded_path",
            )

        if not resolved.is_file():
            raise EditOperationError(
                f"Edit path is not a file: {path}",
                failure_class="invalid_operation",
            )

        if operation.kind == "replace_exact":
            current = resolved.read_text(encoding="utf-8")
            assert operation.old_text is not None
            matches = sum(
                current.startswith(operation.old_text, index)
                for index in range(
                    len(current) - len(operation.old_text) + 1
                )
            )

            if matches == 0:
                raise EditOperationError(
                    f"Exact replacement matched zero times: {path}",
                    failure_class="no_match",
                )

            if matches > 1:
                raise EditOperationError(
                    f"Exact replacement matched {matches} times: {path}",
                    failure_class="ambiguous_match",
                )

            assert operation.new_text is not None
            candidate_contents[path] = current.replace(
                operation.old_text,
                operation.new_text,
                1,
            )
        else:
            candidate_contents[path] = None

    return candidate_contents


def _apply_to_candidate(
    workspace: Workspace,
    response: EditOperationsResponse,
    candidate_contents: dict[str, str | None],
) -> list[str]:
    changed_paths: list[str] = []

    for operation in response.operations:
        path = operation.path
        content = candidate_contents[path]

        if operation.kind == "delete_file":
            resolved = workspace._resolve_safe(path)
            resolved.unlink()
        else:
            assert content is not None
            workspace.write_text(path, content)

        changed_paths.append(path)

    return changed_paths


def _build_diff(
    workspace_root: Path,
    response: EditOperationsResponse,
    grounded_paths: set[str],
) -> str:
    source_workspace = Workspace(workspace_root)
    candidate_contents = _validate_operations(
        source_workspace,
        response,
        grounded_paths,
    )

    with tempfile.TemporaryDirectory(
        prefix=".orchestrator-edit-",
        dir=workspace_root.parent,
    ) as temporary_root:
        candidate = Path(temporary_root) / "candidate"
        candidate.mkdir()
        _run_git(
            candidate,
            "init",
            "-q",
        )
        _run_git(
            candidate,
            "config",
            "user.email",
            "orchestrator@example.invalid",
        )
        _run_git(
            candidate,
            "config",
            "user.name",
            "Local Agent Orchestrator",
        )

        baseline_paths = [
            operation.path
            for operation in response.operations
            if operation.kind != "create_file"
        ]

        for path in baseline_paths:
            source = source_workspace._resolve_safe(path)
            target = (candidate / path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        _run_git(candidate, "add", "-A")
        _run_git(
            candidate,
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        )

        candidate_workspace = Workspace(candidate)
        changed_paths = _apply_to_candidate(
            candidate_workspace,
            response,
            candidate_contents,
        )

        for operation in response.operations:
            if operation.kind == "create_file":
                _run_git(
                    candidate,
                    "add",
                    "-N",
                    "--",
                    operation.path,
                )

        result = _run_git(
            candidate,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--full-index",
            "--",
            *changed_paths,
        )

        if not result.stdout.strip():
            raise EditOperationError(
                "Edit operations produced no workspace changes.",
                failure_class="no_op",
            )

        return result.stdout


def apply_edit_operations(
    workspace_root: str | Path,
    response: EditOperationsResponse,
    *,
    grounded_paths: Iterable[str] | None = None,
) -> list[str]:
    from local_agent_orchestrator.services.diff_patch import apply_unified_diff

    root = Path(workspace_root).resolve()

    if not root.exists():
        raise EditOperationError(
            f"Workspace does not exist: {root}"
        )

    grounded = set(grounded_paths or ())
    patch = _build_diff(root, response, grounded)

    return apply_unified_diff(
        root,
        patch,
        grounded_paths=grounded,
    )
