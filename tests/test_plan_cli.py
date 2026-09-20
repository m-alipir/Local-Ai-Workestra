from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.plan_cli import main


def test_plan_cli_success(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        '{"request":"Build feature","tasks":[{"description":"Task one"}]}'
    )

    fake = MagicMock(
        run_id="run123",
        passed=True,
        completed_tasks=1,
        total_tasks=1,
        commits=["abc123"],
        run_dir=Path("runs/run123"),
        analytics_path=Path("analytics.json"),
        retrospective_path=Path("retrospective.md"),
    )

    with patch(
        "local_agent_orchestrator.plan_cli.run_execution_plan",
        return_value=fake,
    ) as runner:
        code = main([
            "--workspace",
            "/tmp/repo",
            "--plan",
            str(plan_path),
            "--test-command",
            "pytest -q",
        ])

    assert code == 0
    assert runner.call_args.kwargs[
        "test_command"
    ] == ["pytest", "-q"]


def test_plan_cli_reports_missing_plan(capsys):
    with pytest.raises(SystemExit) as raised:
        main([
            "--workspace",
            "/tmp/repo",
            "--plan",
            "/tmp/missing-plan.json",
            "--test-command",
            "pytest -q",
        ])

    assert raised.value.code == 1
    assert "local-agent-plan: error: Plan file not found" in capsys.readouterr().err
