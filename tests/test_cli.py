import tomllib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.cli import main


def test_project_exposes_operational_entrypoints():
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )["project"]

    assert project["version"] == "1.0.0"
    assert set(project["scripts"]) >= {
        "local-agent-orchestrator",
        "local-agent",
        "local-agent-plan",
        "local-agent-control",
        "local-agent-auto",
    }


def test_cli_success():
    fake = MagicMock(
        run_id="run123",
        passed=True,
        attempts=1,
        commit="abc123",
        run_dir=Path("runs/run123"),
        metrics_path=Path("runs/run123/metrics/task.json"),
        analytics_path=Path(".agent/analytics/run123.json"),
        retrospective_path=Path("runs/run123/retrospective.md"),
    )

    with patch(
        "local_agent_orchestrator.cli.run_single_task",
        return_value=fake,
    ) as runner:
        code = main([
            "--workspace",
            "/tmp/repo",
            "--task",
            "Implement feature",
            "--test-command",
            "pytest -q",
        ])

    assert code == 0

    assert runner.call_args.kwargs[
        "test_command"
    ] == ["pytest", "-q"]


def test_cli_reports_runtime_errors_without_traceback(capsys):
    with patch(
        "local_agent_orchestrator.cli.run_single_task",
        side_effect=RuntimeError("target is not a Git repository"),
    ), pytest.raises(SystemExit) as raised:
        main([
            "--workspace",
            "/tmp/repo",
            "--task",
            "Implement feature",
            "--test-command",
            "pytest -q",
        ])

    assert raised.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == (
        "local-agent: error: target is not a Git repository\n"
    )
    assert "Traceback" not in captured.err
