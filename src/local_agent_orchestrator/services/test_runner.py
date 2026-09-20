from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    passed: bool
    returncode: int
    stdout: str
    stderr: str


def verification_environment(root: Path) -> dict[str, str]:
    root = Path(root).resolve()
    environment = os.environ.copy()
    for variable in (
        "PYTHONHOME",
        "PYTHONPATH",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
    ):
        environment.pop(variable, None)

    paths_to_remove: set[Path] = set()
    interpreter_bin = Path(sys.executable).resolve().parent

    if (interpreter_bin.parent / "pyvenv.cfg").is_file():
        paths_to_remove.add(interpreter_bin)

    active_virtualenv = environment.get("VIRTUAL_ENV")

    if active_virtualenv:
        active_root = Path(active_virtualenv).expanduser().resolve()
        paths_to_remove.add(active_root / "bin")
        paths_to_remove.add(active_root / "Scripts")

    path_entries = environment.get("PATH", "").split(os.pathsep)
    filtered_path = [
        entry
        for entry in path_entries
        if not entry
        or Path(entry).expanduser().resolve() not in paths_to_remove
    ]

    target_virtualenv = root / ".venv"

    if target_virtualenv.is_dir():
        target_bin = target_virtualenv / (
            "Scripts" if os.name == "nt" else "bin"
        )

        if target_bin.is_dir():
            filtered_path.insert(0, str(target_bin))

        environment["VIRTUAL_ENV"] = str(target_virtualenv)
    else:
        environment.pop("VIRTUAL_ENV", None)

    environment["PATH"] = os.pathsep.join(filtered_path)
    return environment


def run_tests(
    workspace_root: str | Path,
    command: list[str],
    timeout: int = 120,
) -> CommandResult:
    root = Path(workspace_root).resolve()

    process = subprocess.run(
        command,
        cwd=root,
        env=verification_environment(root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    return CommandResult(
        passed=process.returncode == 0,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )
