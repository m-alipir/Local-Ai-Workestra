from __future__ import annotations

import re
import subprocess
from pathlib import Path
from collections.abc import Iterable


class DiffPatchError(RuntimeError):
    pass


DIFF_PATH_RE = re.compile(
    r"^diff --git a/(.+?) b/(.+?)$",
    re.MULTILINE,
)


def extract_patch_paths(patch: str) -> tuple[list[str], set[str]]:
    """Return referenced paths and paths explicitly created by the patch."""
    headers = list(DIFF_PATH_RE.finditer(patch))

    if not headers and "diff --git " in patch:
        raise DiffPatchError("Malformed diff path header.")
    if not headers:
        raise DiffPatchError("Patch contains no valid git diff file headers.")

    paths: list[str] = []
    new_paths: set[str] = set()

    for index, header in enumerate(headers):
        old_path, new_path = header.groups()
        _validate_relative_path(old_path)
        _validate_relative_path(new_path)

        block_end = (
            headers[index + 1].start()
            if index + 1 < len(headers)
            else len(patch)
        )
        block = patch[header.start():block_end]
        old_is_null = "--- /dev/null" in block
        new_is_null = "+++ /dev/null" in block
        is_new_file = old_is_null or "new file mode " in block

        if not old_is_null and old_path not in paths:
            paths.append(old_path)
        if not new_is_null and new_path not in paths:
            paths.append(new_path)

        if is_new_file and not new_is_null:
            new_paths.add(new_path)

    return paths, new_paths


def _validate_relative_path(path: str) -> None:
    candidate = Path(path)

    if candidate.is_absolute():
        raise DiffPatchError(
            f"Absolute path is not allowed: {path}"
        )

    if ".." in candidate.parts:
        raise DiffPatchError(
            f"Parent traversal is not allowed: {path}"
        )


def extract_changed_files(patch: str) -> list[str]:
    files: list[str] = []
    headers = list(DIFF_PATH_RE.finditer(patch))
    extract_patch_paths(patch)

    for index, header in enumerate(headers):
        old_path, new_path = header.groups()
        block_end = (
            headers[index + 1].start()
            if index + 1 < len(headers)
            else len(patch)
        )
        target = old_path if "+++ /dev/null" in patch[header.start():block_end] else new_path

        if target not in files:
            files.append(target)

    if not files:
        raise DiffPatchError(
            "Patch contains no valid git diff file headers."
        )

    return files


def _validate_grounded_paths(
    patch: str,
    grounded_paths: Iterable[str],
) -> None:
    paths, new_paths = extract_patch_paths(patch)
    grounded = set(grounded_paths)
    missing = sorted(
        path
        for path in paths
        if path not in new_paths and path not in grounded
    )

    if missing:
        raise DiffPatchError(
            "Patch paths are not grounded in repository evidence: "
            + ", ".join(missing)
        )


def apply_unified_diff(
    workspace_root: str | Path,
    patch: str,
    *,
    grounded_paths: Iterable[str] | None = None,
) -> list[str]:
    root = Path(workspace_root).resolve()

    if not root.exists():
        raise DiffPatchError(
            f"Workspace does not exist: {root}"
        )

    changed_files = extract_changed_files(patch)

    if grounded_paths is not None:
        _validate_grounded_paths(patch, grounded_paths)

    check = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "apply",
            "--check",
            "--recount",
            "--whitespace=error",
            "-",
        ],
        input=patch,
        capture_output=True,
        text=True,
    )

    if check.returncode != 0:
        raise DiffPatchError(
            check.stderr.strip()
            or check.stdout.strip()
            or "Patch validation failed."
        )

    apply = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "apply",
            "--recount",
            "--whitespace=error",
            "-",
        ],
        input=patch,
        capture_output=True,
        text=True,
    )

    if apply.returncode != 0:
        raise DiffPatchError(
            apply.stderr.strip()
            or apply.stdout.strip()
            or "Patch apply failed."
        )

    return changed_files
