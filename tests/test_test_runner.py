import sys
from types import SimpleNamespace
from unittest.mock import patch

from local_agent_orchestrator.services.test_runner import run_tests


def test_successful_command(tmp_path):
    result = run_tests(
        tmp_path,
        ["python", "-c", "print(123)"],
    )

    assert result.passed is True
    assert result.returncode == 0
    assert "123" in result.stdout


def test_failed_command(tmp_path):
    result = run_tests(
        tmp_path,
        [
            "python",
            "-c",
            "import sys; print('fail'); sys.exit(1)",
        ],
    )

    assert result.passed is False
    assert result.returncode == 1
    assert "fail" in result.stdout


def test_verification_command_runs_from_target_workspace(tmp_path):
    target = tmp_path / "target-project"
    target.mkdir()
    (target / "pyproject.toml").write_text(
        "[project]\nname = 'target-project'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    (target / "workspace-marker.txt").write_text(
        "target\n",
        encoding="utf-8",
    )

    result = run_tests(
        target,
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "assert Path('workspace-marker.txt').read_text() == 'target\\n'; "
                "print(Path.cwd())"
            ),
        ],
    )

    assert result.passed is True
    assert str(target.resolve()) in result.stdout


def test_verification_prefers_target_virtualenv_over_orchestrator(tmp_path):
    target = tmp_path / "target-project"
    target_bin = target / ".venv" / "bin"
    target_bin.mkdir(parents=True)

    pytest_shim = target_bin / "pytest"
    pytest_shim.write_text(
        "#!/bin/sh\n"
        "printf 'cwd=%s\\n' \"$PWD\"\n"
        "printf 'venv=%s\\n' \"$VIRTUAL_ENV\"\n",
        encoding="utf-8",
    )
    pytest_shim.chmod(0o755)

    result = run_tests(target, ["pytest"])

    assert result.passed is True
    assert f"cwd={target.resolve()}" in result.stdout
    assert f"venv={target / '.venv'}" in result.stdout


def test_repeated_verification_uses_the_same_target_environment(tmp_path):
    target_bin = tmp_path / ".venv" / "bin"
    target_bin.mkdir(parents=True)
    pytest_shim = target_bin / "pytest"
    pytest_shim.write_text("#!/bin/sh\n", encoding="utf-8")
    pytest_shim.chmod(0o755)
    calls = []

    def fake_run(command, *, cwd, env, **kwargs):
        calls.append((command, cwd, env))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch(
        "local_agent_orchestrator.services.test_runner.subprocess.run",
        side_effect=fake_run,
    ):
        run_tests(tmp_path, ["pytest", "-q"])
        run_tests(tmp_path, ["pytest", "-q"])

    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] == ["pytest", "-q"]
    assert calls[0][1] == calls[1][1] == tmp_path.resolve()
    assert calls[0][2] == calls[1][2]
    assert calls[0][2]["VIRTUAL_ENV"] == str(tmp_path / ".venv")


def test_verification_environment_uses_only_target_pythonpath_and_disables_bytecode(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/orchestrator-only")

    with patch(
        "local_agent_orchestrator.services.test_runner.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
    ) as runner:
        run_tests(tmp_path, ["python", "-c", "print('ok')"])

    environment = runner.call_args.kwargs["env"]
    assert environment["PYTHONPATH"] == str(tmp_path.resolve())
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "/orchestrator-only" not in environment["PYTHONPATH"]
