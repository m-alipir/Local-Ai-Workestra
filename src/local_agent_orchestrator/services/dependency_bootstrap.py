from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from local_agent_orchestrator.services.test_runner import (
    verification_environment,
)


_PACKAGE_NAME_RE = re.compile(r"[<>=!~;\[\s]")
_PYTHON_NAMES = {"python", "python3", "python.exe", "python3.exe"}


class VerificationBootstrapError(RuntimeError):
    """A target verification environment could not be prepared safely."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    status: str
    command: tuple[str, ...] | None = None
    stdout: str = ""
    stderr: str = ""


def _normalise_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def _dependency_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    return _PACKAGE_NAME_RE.split(value, maxsplit=1)[0] or None


def _contains_dependency(values: object, requested_tool: str) -> bool:
    if not isinstance(values, list):
        return False

    requested = _normalise_package_name(requested_tool)

    return any(
        _normalise_package_name(name) == requested
        for value in values
        if (name := _dependency_name(value)) is not None
    )


def _requested_tool(command: list[str]) -> str:
    if not command:
        raise VerificationBootstrapError(
            "invalid_command",
            "verification command is empty",
        )

    tokens = list(command)
    first_name = Path(tokens[0]).name.lower()

    if first_name in {"uv", "uv.exe"}:
        if len(tokens) < 3 or tokens[1] != "run":
            raise VerificationBootstrapError(
                "unsupported_command",
                "only `uv run <verification-tool>` commands are supported",
            )
        tokens = tokens[2:]

    if (
        Path(tokens[0]).name.lower() in _PYTHON_NAMES
        and len(tokens) >= 3
        and tokens[1] == "-m"
    ):
        return Path(tokens[2]).name

    return Path(tokens[0]).name


def _target_bin(root: Path) -> Path:
    return root / ".venv" / ("Scripts" if os.name == "nt" else "bin")


def _target_tool_available(root: Path, tool: str) -> bool:
    names = [tool]
    if os.name == "nt" and not tool.lower().endswith(".exe"):
        names.append(f"{tool}.exe")

    for name in names:
        executable = _target_bin(root) / name
        try:
            resolved = executable.resolve()
            target_root = (root / ".venv").resolve()
            resolved.relative_to(target_root)

            if executable.is_file() and (
                os.name == "nt" or executable.stat().st_mode & 0o111 != 0
            ):
                return True
        except (OSError, ValueError):
            continue

    return False


def _metadata_bootstrap_command(root: Path, tool: str) -> list[str]:
    pyproject = root / "pyproject.toml"
    lockfile = root / "uv.lock"

    if not pyproject.is_file() or not lockfile.is_file():
        raise VerificationBootstrapError(
            "missing_metadata",
            "safe bootstrap requires pyproject.toml and uv.lock in the target",
        )

    try:
        with pyproject.open("rb") as handle:
            metadata = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise VerificationBootstrapError(
            "invalid_metadata",
            f"could not read target pyproject.toml: {exc}",
        ) from exc

    project = metadata.get("project", {})
    if not isinstance(project, dict):
        raise VerificationBootstrapError(
            "invalid_metadata",
            "target pyproject.toml has no valid [project] table",
        )

    if _contains_dependency(project.get("dependencies"), tool):
        return ["uv", "sync", "--locked"]

    optional_dependencies = project.get("optional-dependencies", {})
    if isinstance(optional_dependencies, dict) and _contains_dependency(
        optional_dependencies.get("dev"),
        tool,
    ):
        return ["uv", "sync", "--locked", "--extra", "dev"]

    dependency_groups = metadata.get("dependency-groups", {})
    if isinstance(dependency_groups, dict) and _contains_dependency(
        dependency_groups.get("dev"),
        tool,
    ):
        return ["uv", "sync", "--locked", "--group", "dev"]

    raise VerificationBootstrapError(
        "unsupported_dependency",
        f"trusted target metadata does not declare verification tool `{tool}`",
    )


def prepare_verification_environment(
    workspace_root: str | Path,
    command: list[str],
    timeout: int = 300,
) -> BootstrapResult:
    """Reuse or safely prepare the target environment for verification.

    Only a locked uv project is currently supported for installation. The
    install command is fixed by this service; no model-provided command is
    executed.
    """

    root = Path(workspace_root).resolve()
    tool = _requested_tool(command)

    if _target_tool_available(root, tool):
        return BootstrapResult(status="reused")

    bootstrap_command = _metadata_bootstrap_command(root, tool)
    environment = verification_environment(root)

    try:
        process = subprocess.run(
            bootstrap_command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise VerificationBootstrapError(
            "bootstrap_spawn_failed",
            f"could not start trusted bootstrap command: {exc}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise VerificationBootstrapError(
            "bootstrap_timeout",
            f"trusted bootstrap exceeded {timeout}s",
        ) from exc

    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise VerificationBootstrapError(
            "bootstrap_failed",
            f"trusted bootstrap exited with code {process.returncode}{suffix}",
        )

    if not _target_tool_available(root, tool):
        raise VerificationBootstrapError(
            "bootstrap_incomplete",
            f"bootstrap completed but target tool `{tool}` is still unavailable",
        )

    return BootstrapResult(
        status="bootstrapped",
        command=tuple(bootstrap_command),
        stdout=process.stdout,
        stderr=process.stderr,
    )


def assert_verification_environment_supported(
    workspace_root: str | Path,
    command: list[str],
) -> None:
    """Check start-time verifier support without changing the target."""

    root = Path(workspace_root).resolve()
    tool = _requested_tool(command)
    if _target_tool_available(root, tool):
        return
    _metadata_bootstrap_command(root, tool)
