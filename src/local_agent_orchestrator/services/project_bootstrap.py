from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.services.test_runner import verification_environment


PYTHON_UV_VERIFIER = ("uv", "run", "pytest", "-q")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
_PROFILES = {
    "python": "dependencies = []",
    "fastapi": 'dependencies = ["fastapi>=0.115,<1", "sqlalchemy>=2,<3"]',
}


class ProjectBootstrapError(RuntimeError):
    """A bounded project bootstrap could not be completed."""


@dataclass(frozen=True, slots=True)
class ProjectBootstrapResult:
    workspace_root: Path
    test_command: tuple[str, ...]
    created_files: tuple[str, ...]


def bootstrap_python_project(
    workspace_root: str | Path,
    name: str,
    *,
    profile: str = "python",
) -> ProjectBootstrapResult:
    """Create the supported, dependency-locked Python project baseline.

    The target must be missing or empty. Every subprocess command is fixed in
    this module; no caller or model supplied command is accepted.
    """

    requested_root = Path(workspace_root).expanduser()
    if requested_root.is_symlink():
        raise ProjectBootstrapError("bootstrap target cannot be a symlink")
    root = requested_root.resolve()
    if not isinstance(name, str) or not name.strip() or not _SAFE_NAME.fullmatch(name.strip()):
        raise ProjectBootstrapError(
            "project name must contain only letters, numbers, spaces, dots, underscores, or hyphens"
        )
    if profile not in _PROFILES:
        raise ProjectBootstrapError("bootstrap profile must be python or fastapi")

    root_was_missing = not root.exists()
    if root.exists():
        if not root.is_dir():
            raise ProjectBootstrapError(f"bootstrap target is not a directory: {root}")
        if any(root.iterdir()):
            raise ProjectBootstrapError(f"bootstrap target must be empty or missing (non-empty): {root}")
    else:
        root.mkdir(parents=True)

    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ProjectBootstrapError("project name must produce a valid package name")

    files = {
        "pyproject.toml": (
            "[project]\n"
            f'name = "{slug}"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.12"\n'
            f"{_PROFILES[profile]}\n\n"
            "[dependency-groups]\n"
            'dev = ["pytest>=9.1,<10", "httpx>=0.27,<1"]\n'
        ),
        ".gitignore": ".venv/\n__pycache__/\n*.py[cod]\n.pytest_cache/\n",
        "tests/test_bootstrap.py": (
            "def test_bootstrap_smoke():\n"
            "    assert True\n"
        ),
    }
    commands = (
        ["git", "init", "-q"],
        ["uv", "lock"],
        ["uv", "sync", "--locked"],
        [
            "git",
            "add",
            "--",
            ".gitignore",
            "pyproject.toml",
            "uv.lock",
            "tests/test_bootstrap.py",
        ],
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Workestra",
            "-c",
            "user.email=workestra@localhost",
            "commit",
            "-qm",
            "Initialize Workestra Python project",
        ],
    )
    try:
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(content)
            except FileExistsError as exc:
                raise ProjectBootstrapError(
                    f"bootstrap target changed while preparing: {path}"
                ) from exc

        environment = verification_environment(root)
        for command in commands:
            try:
                process = subprocess.run(
                    command,
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                raise ProjectBootstrapError(
                    f"trusted bootstrap command failed ({command[0]}): {detail.strip()}"
                ) from exc
            if process.returncode != 0:
                raise ProjectBootstrapError(
                    f"trusted bootstrap command failed ({command[0]}) with code {process.returncode}"
                )
    except Exception:
        _cleanup_failed_bootstrap(root, files, root_was_missing)
        raise

    return ProjectBootstrapResult(
        workspace_root=root,
        test_command=PYTHON_UV_VERIFIER,
        created_files=tuple(files),
    )


def _cleanup_failed_bootstrap(
    root: Path,
    files: dict[str, str],
    root_was_missing: bool,
) -> None:
    for relative in (*files, "uv.lock"):
        path = root / relative
        if path.is_file():
            path.unlink()
    for relative in (".git", ".venv"):
        path = root / relative
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    tests = root / "tests"
    if tests.is_dir() and not any(tests.iterdir()):
        tests.rmdir()
    if root_was_missing and root.is_dir() and not any(root.iterdir()):
        root.rmdir()
