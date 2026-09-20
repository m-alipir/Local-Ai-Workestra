from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.control_cli import main


def test_control_cli_approve():
    with patch(
        "local_agent_orchestrator.control_cli.approve_waiting_task",
        return_value="task-002",
    ) as approve:
        code = main([
            "approve",
            "run123",
            "--runs-dir",
            "runs-test",
        ])

    assert code == 0

    approve.assert_called_once_with(
        run_id="run123",
        runs_dir="runs-test",
        task_id=None,
    )


def test_control_cli_resume_success():
    result = MagicMock(
        run_id="run123",
        waiting_for_approval=False,
        waiting_task_id=None,
        passed=True,
        completed_tasks=2,
        total_tasks=2,
        commits=["a", "b"],
    )

    with patch(
        "local_agent_orchestrator.control_cli.resume_execution_plan",
        return_value=result,
    ) as resume:
        code = main([
            "resume",
            "run123",
            "--workspace",
            "/tmp/repo",
            "--test-command",
            "pytest -q",
        ])

    assert code == 0

    assert resume.call_args.kwargs[
        "test_command"
    ] == ["pytest", "-q"]


def test_control_cli_resume_waiting():
    result = MagicMock(
        run_id="run123",
        waiting_for_approval=True,
        waiting_task_id="task-003",
        passed=False,
        completed_tasks=2,
        total_tasks=4,
        commits=[],
    )

    with patch(
        "local_agent_orchestrator.control_cli.resume_execution_plan",
        return_value=result,
    ):
        code = main([
            "resume",
            "run123",
            "--workspace",
            "/tmp/repo",
            "--test-command",
            "pytest -q",
        ])

    assert code == 2


def test_control_cli_reports_missing_run(capsys):
    with pytest.raises(SystemExit) as raised:
        main([
            "approve",
            "missing-run",
            "--runs-dir",
            "/tmp/missing-runs",
        ])

    assert raised.value.code == 1
    assert "local-agent-control: error: Run not found" in capsys.readouterr().err
