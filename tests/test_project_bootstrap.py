from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from local_agent_orchestrator.services.project_bootstrap import (
    ProjectBootstrapError,
    bootstrap_python_project,
)


def test_bootstrap_python_project_creates_locked_git_ready_target(tmp_path):
    target = tmp_path / "new-project"

    def fake_run(command, *, cwd, env, capture_output, text, check):
        assert cwd == target.resolve()
        assert capture_output is True
        assert text is True
        assert check is True
        if command[:2] == ["uv", "lock"]:
            (target / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch(
        "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
        side_effect=fake_run,
    ) as run:
        result = bootstrap_python_project(target, "Demo Project")

    assert result.test_command == ("uv", "run", "pytest", "-q")
    assert (target / "pyproject.toml").is_file()
    assert (target / "tests" / "test_bootstrap.py").is_file()
    assert (target / ".gitignore").is_file()
    assert [call.args[0] for call in run.call_args_list] == [
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
    ]


def test_bootstrap_refuses_existing_nonempty_target(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ProjectBootstrapError, match="non-empty"):
        bootstrap_python_project(target, "Demo")

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_bootstrap_rejects_unsafe_project_name(tmp_path):
    with pytest.raises(ProjectBootstrapError, match="project name"):
        bootstrap_python_project(tmp_path / "new", "../../run-command")


def test_fastapi_profile_is_fixed_trusted_metadata(tmp_path):
    target = tmp_path / "fastapi"
    with patch(
        "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    ):
        bootstrap_python_project(target, "Notes", profile="fastapi")
    assert 'dependencies = ["fastapi>=0.115,<1", "sqlalchemy>=2,<3"]' in (target / "pyproject.toml").read_text()
    assert '"httpx>=0.27,<1"' in (target / "pyproject.toml").read_text()

    with pytest.raises(ProjectBootstrapError, match="profile"):
        bootstrap_python_project(tmp_path / "unsupported", "Notes", profile="anything")


def test_bootstrap_does_not_run_model_or_shell_commands(tmp_path):
    target = tmp_path / "new"

    with patch(
        "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    ) as run:
        bootstrap_python_project(target, "Demo")

    assert all(isinstance(call.args[0], list) for call in run.call_args_list)
    assert all("shell" not in call.kwargs for call in run.call_args_list)


def test_bootstrap_failure_cleans_only_its_new_target(tmp_path):
    target = tmp_path / "failed"

    def fail_on_lock(command, **kwargs):
        if command[:2] == ["uv", "lock"]:
            raise subprocess.CalledProcessError(1, command, stderr="lock failed")
        return subprocess.CompletedProcess(command, 0, "", "")

    with patch(
        "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
        side_effect=fail_on_lock,
    ):
        with pytest.raises(ProjectBootstrapError, match="trusted bootstrap command failed"):
            bootstrap_python_project(target, "Failed Project")

    assert not target.exists()
