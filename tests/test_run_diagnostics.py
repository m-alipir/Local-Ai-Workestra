from __future__ import annotations

import json

from local_agent_orchestrator.services.run_diagnostics import (
    collect_run_diagnostics,
)


def _write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_collect_run_diagnostics_combines_bounded_failure_evidence(tmp_path):
    run_dir = tmp_path / "run-123"
    (run_dir / "metrics").mkdir(parents=True)
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-123",
            "request": "Implement feature",
            "status": "failed",
            "current_task": "task-001",
            "tasks": [
                {
                    "id": "task-001",
                    "description": "Implement feature",
                    "status": "failed",
                    "error": "STDOUT:\n" + "out " * 100 + "\n\nSTDERR:\nassertion failed",
                }
            ],
        },
    )
    _write_json(
        run_dir / "metrics" / "task-001.json",
        {
            "task_id": "task-001",
            "description": "Implement feature",
            "passed": False,
            "test_returncode": 1,
            "commit": None,
            "operation_failures": [
                {
                    "model": "qwen_coder",
                    "attempt": 2,
                    "failure_class": "no_match",
                    "detail": "Exact replacement failed",
                }
            ],
            "verification_classification": "new_failures",
        },
    )
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "run_id": "run-123",
                    "task_id": "task-001",
                    "event": "model_attempt_failed",
                    "model": "qwen_coder",
                    "attempt": 2,
                    "failure_class": "invalid_operation",
                    "detail": "model backend detail",
                },
                {
                    "run_id": "run-123",
                    "task_id": "task-001",
                    "event": "verification_finished",
                    "passed": False,
                    "detail": "returncode=1\nSTDOUT:\n" + "x" * 200 + "\nSTDERR:\nboom",
                },
                {
                    "run_id": "run-123",
                    "task_id": "task-001",
                    "event": "checkpoint_failed",
                    "passed": False,
                    "detail": "Checkpoint failed: hook rejected",
                },
                {
                    "run_id": "run-123",
                    "task_id": "task-001",
                    "event": "rollback",
                    "passed": True,
                    "detail": "workspace restored",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "request.md").write_text("request", encoding="utf-8")
    (run_dir / "extra.log").write_text("extra", encoding="utf-8")

    diagnostics = collect_run_diagnostics(
        run_dir,
        max_text_chars=40,
        max_events=3,
        max_artifacts=2,
    )

    assert diagnostics["run_id"] == "run-123"
    assert diagnostics["failure_class"] == "checkpoint_failure"
    assert diagnostics["failing_task"] == {
        "id": "task-001",
        "description": "Implement feature",
        "status": "failed",
    }
    assert len(diagnostics["events"]) == 3
    assert diagnostics["verifier"]["returncode"] == 1
    assert len(diagnostics["verifier"]["stdout"]) <= 40
    assert diagnostics["verifier"]["stderr"] == "boom"
    assert diagnostics["model_errors"][0]["failure_class"] == "invalid_operation"
    assert diagnostics["checkpoint"] == {
        "commit": None,
        "created": False,
        "failed": True,
        "rollback_observed": True,
    }
    assert len(diagnostics["artifacts"]) == 2
    assert diagnostics["artifacts_omitted"] == 3
    assert diagnostics["summary"].startswith("Run run-123 failed")
    assert "Verification: new_failures" in diagnostics["summary"]


def test_collect_run_diagnostics_preserves_unlabelled_verifier_detail(tmp_path):
    run_dir = tmp_path / "run-raw"
    run_dir.mkdir()
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-raw",
            "status": "failed",
            "tasks": [{"id": "task-001", "description": "test", "status": "failed", "error": "FAILED test_demo.py::test_one\nverifier output"}],
        },
    )
    diagnostics = collect_run_diagnostics(run_dir)
    assert "FAILED test_demo.py::test_one" in diagnostics["verifier"]["stderr"]


def test_collect_run_diagnostics_reports_passed_run_without_failure(tmp_path):
    run_dir = tmp_path / "run-456"
    run_dir.mkdir()
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-456",
            "request": "Pass",
            "status": "passed",
            "tasks": [
                {
                    "id": "task-001",
                    "description": "Pass",
                    "status": "passed",
                }
            ],
        },
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["failure_class"] == "none"
    assert diagnostics["failing_task"] is None
    assert diagnostics["summary"] == "Run run-456 passed."
