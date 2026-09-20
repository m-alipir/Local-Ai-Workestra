import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from local_agent_orchestrator.services.dependency_bootstrap import (
    VerificationBootstrapError,
    prepare_verification_environment,
)


def write_metadata(root, *, dev_dependency="pytest>=9"):
    (root / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'target'\n"
        "version = '0.0.0'\n"
        "requires-python = '>=3.12'\n"
        f"dependencies = []\n\n"
        "[project.optional-dependencies]\n"
        f"dev = ['{dev_dependency}']\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        "version = 1\nrevision = 1\n",
        encoding="utf-8",
    )


def add_target_tool(root, name="pytest"):
    tool = root / ".venv" / "bin" / name
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)


def test_existing_target_venv_with_pytest_is_reused(tmp_path):
    add_target_tool(tmp_path)

    with patch(
        "local_agent_orchestrator.services.dependency_bootstrap.subprocess.run"
    ) as run:
        result = prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert result.status == "reused"
    run.assert_not_called()


def test_external_target_tool_symlink_is_not_reused(tmp_path):
    target_bin = tmp_path / ".venv" / "bin"
    target_bin.mkdir(parents=True)
    external_tool = tmp_path / "orchestrator-pytest"
    external_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    external_tool.chmod(0o755)
    (target_bin / "pytest").symlink_to(external_tool)

    with pytest.raises(VerificationBootstrapError) as raised:
        prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "missing_metadata"


def test_target_without_venv_requires_supported_metadata(tmp_path):
    with pytest.raises(VerificationBootstrapError) as raised:
        prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "missing_metadata"
    assert not (tmp_path / ".venv").exists()


def test_bootstrap_success_uses_locked_dev_metadata(tmp_path):
    write_metadata(tmp_path)
    observed = {}

    def fake_run(command, *, cwd, env, capture_output, text, timeout):
        observed.update(
            command=command,
            cwd=cwd,
            env=env,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
        )
        add_target_tool(tmp_path)
        return SimpleNamespace(returncode=0, stdout="synced\n", stderr="")

    with patch(
        "local_agent_orchestrator.services.dependency_bootstrap.subprocess.run",
        side_effect=fake_run,
    ):
        result = prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert result.status == "bootstrapped"
    assert result.command == ("uv", "sync", "--locked", "--extra", "dev")
    assert observed["command"] == ["uv", "sync", "--locked", "--extra", "dev"]
    assert observed["cwd"] == tmp_path.resolve()
    assert observed["capture_output"] is True
    assert observed["text"] is True
    assert observed["timeout"] == 300


def test_bootstrap_supports_dependency_groups_dev(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'target'\n"
        "version = '0.0.0'\n"
        "requires-python = '>=3.12'\n"
        "dependencies = []\n\n"
        "[dependency-groups]\n"
        "dev = ['pytest>=9']\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        "version = 1\nrevision = 1\n",
        encoding="utf-8",
    )

    def fake_run(*args, **kwargs):
        add_target_tool(tmp_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch(
        "local_agent_orchestrator.services.dependency_bootstrap.subprocess.run",
        side_effect=fake_run,
    ) as run:
        result = prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert result.command == ("uv", "sync", "--locked", "--group", "dev")
    assert run.call_args.args[0] == ["uv", "sync", "--locked", "--group", "dev"]


def test_bootstrap_failure_is_controlled(tmp_path):
    write_metadata(tmp_path)

    with patch(
        "local_agent_orchestrator.services.dependency_bootstrap.subprocess.run",
        return_value=SimpleNamespace(
            returncode=17,
            stdout="",
            stderr="network unavailable",
        ),
    ):
        with pytest.raises(VerificationBootstrapError) as raised:
            prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "bootstrap_failed"
    assert "network unavailable" in raised.value.detail
    assert not (tmp_path / ".venv" / "bin" / "pytest").exists()


def test_unsupported_or_missing_dependency_metadata_fails_closed(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "pytest==9.0.0\n",
        encoding="utf-8",
    )

    with pytest.raises(VerificationBootstrapError) as raised:
        prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "missing_metadata"

    write_metadata(tmp_path, dev_dependency="ruff>=0.9")

    with pytest.raises(VerificationBootstrapError) as raised:
        prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert raised.value.code == "unsupported_dependency"


def test_bootstrap_does_not_leak_orchestrator_environment(tmp_path, monkeypatch):
    write_metadata(tmp_path)
    orchestrator_bin = tmp_path / "orchestrator-venv" / "bin"
    orchestrator_bin.mkdir(parents=True)
    (orchestrator_bin.parent / "pyvenv.cfg").write_text(
        "home = /usr/bin\n",
        encoding="utf-8",
    )
    system_bin = tmp_path / "system-bin"
    system_bin.mkdir()

    monkeypatch.setattr(
        sys,
        "executable",
        str(orchestrator_bin / "python"),
    )
    monkeypatch.setenv("VIRTUAL_ENV", str(orchestrator_bin.parent))
    monkeypatch.setenv("PYTHONPATH", str(orchestrator_bin.parent / "lib"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(orchestrator_bin.parent))
    monkeypatch.setenv("UV_PYTHON", str(orchestrator_bin / "python"))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(orchestrator_bin), str(system_bin)]),
    )

    observed = {}

    def fake_run(command, *, cwd, env, **kwargs):
        observed.update(command=command, cwd=cwd, env=env)
        add_target_tool(tmp_path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch(
        "local_agent_orchestrator.services.dependency_bootstrap.subprocess.run",
        side_effect=fake_run,
    ):
        prepare_verification_environment(tmp_path, ["pytest", "-q"])

    assert observed["cwd"] == tmp_path.resolve()
    assert observed["env"].get("VIRTUAL_ENV") is None
    assert observed["env"].get("PYTHONPATH") is None
    assert observed["env"].get("UV_PROJECT_ENVIRONMENT") is None
    assert observed["env"].get("UV_PYTHON") is None
    assert str(orchestrator_bin) not in observed["env"]["PATH"].split(os.pathsep)
    assert str(system_bin) in observed["env"]["PATH"].split(os.pathsep)
