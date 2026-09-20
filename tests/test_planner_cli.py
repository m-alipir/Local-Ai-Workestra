from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.planner_cli import main


def test_planner_cli_success():
    fake_run = MagicMock(
        run_id="run123",
        passed=True,
        completed_tasks=2,
        total_tasks=2,
        commits=["a", "b"],
        retrospective_path=Path("retrospective.md"),
    )

    fake = MagicMock(
        plan_path=Path("plan.json"),
        run=fake_run,
    )

    with patch(
        "local_agent_orchestrator.planner_cli.run_planned_request",
        return_value=fake,
    ):
        code = main([
            "--workspace",
            "/tmp/repo",
            "--request",
            "Build feature",
            "--test-command",
            "pytest -q",
        ])

    assert code == 0


def test_planner_cli_reports_planner_failure(capsys):
    with (
        patch(
            "local_agent_orchestrator.planner_cli.run_planned_request",
            side_effect=RuntimeError("planner unavailable"),
        ),
        pytest.raises(SystemExit) as raised,
    ):
        main([
            "--workspace",
            "/tmp/repo",
            "--request",
            "Build feature",
            "--test-command",
            "pytest -q",
        ])

    assert raised.value.code == 1
    assert "local-agent-auto: error: planner unavailable" in capsys.readouterr().err
