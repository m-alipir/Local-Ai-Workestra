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


def test_coding_schema_failure_is_not_reported_as_verifier_failure(tmp_path):
    run_dir = tmp_path / "run-schema-failure"
    (run_dir / "metrics").mkdir(parents=True)
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-schema-failure",
            "status": "failed",
            "tasks": [
                {"id": "task-001", "description": "build app", "status": "passed"},
                {
                    "id": "task-002",
                    "description": "add validation",
                    "status": "failed",
                    "error": "STDERR:\nCoding output could not be safely applied: duplicate paths",
                    "verification_status": "not_requested",
                },
            ],
        },
    )
    _write_json(
        run_dir / "metrics" / "task-001.json",
        {
            "task_id": "task-001",
            "test_returncode": 0,
            "verification_classification": "passed",
        },
    )
    _write_json(
        run_dir / "metrics" / "task-002.json",
        {
            "task_id": "task-002",
            "test_returncode": 1,
            "baseline_returncode": 0,
            "baseline_passed": True,
            "verification_classification": None,
            "operation_failures": [
                {
                    "model": "qwen_coder",
                    "attempt": 1,
                    "failure_class": "invalid_schema",
                    "detail": "operations must not contain duplicate paths",
                }
            ],
        },
    )
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "run_id": "run-schema-failure",
                    "task_id": "task-001",
                    "event": "tests_finished",
                    "passed": True,
                    "detail": "returncode=0\nSTDOUT:\n1 passed\nSTDERR:\n",
                },
                {
                    "run_id": "run-schema-failure",
                    "task_id": "task-002",
                    "event": "coding_output_rejected",
                    "model": "qwen_coder",
                    "attempt": 1,
                    "failure_class": "invalid_schema",
                    "detail": "operations must not contain duplicate paths",
                },
                {
                    "run_id": "run-schema-failure",
                    "task_id": "task-002",
                    "event": "task_completed",
                    "passed": False,
                    "detail": "STDERR:\\nCoding output could not be safely applied: duplicate paths",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["failure_class"] == "operation_failure"
    assert diagnostics["verifier"] == {
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "classification": None,
        "baseline_returncode": 0,
        "baseline_passed": True,
    }
    assert diagnostics["model_errors"][0]["failure_class"] == "invalid_schema"
    task_errors = [
        error for error in diagnostics["model_errors"]
        if error.get("task_id") == "task-002"
    ]
    assert len(task_errors) == 1
    assert task_errors[0]["attempt"] == 1


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


def test_collect_run_diagnostics_keeps_active_retry_nonterminal(tmp_path):
    run_dir = tmp_path / "run-active"
    run_dir.mkdir()
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-active",
            "status": "running",
            "current_task": "task-001",
            "tasks": [
                {
                    "id": "task-001",
                    "description": "retry",
                    "status": "running",
                }
            ],
        },
    )
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in [
                {
                    "run_id": "run-active",
                    "task_id": "task-001",
                    "event": "coding_output_rejected",
                    "model": "qwen_coder",
                    "attempt": 1,
                    "failure_class": "no_match",
                    "detail": "retryable operation rejection",
                },
                {
                    "run_id": "run-active",
                    "task_id": "task-001",
                    "event": "model_attempt_started",
                    "model": "qwen_coder",
                    "attempt": 2,
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["status"] == "running"
    assert diagnostics["failure_class"] == "in_progress"
    assert diagnostics["summary"] == "Run run-active is still in progress."
    assert [error["event"] for error in diagnostics["model_errors"]] == [
        "coding_output_rejected"
    ]


def test_collect_run_diagnostics_does_not_treat_model_start_as_error(tmp_path):
    run_dir = tmp_path / "run-start"
    run_dir.mkdir()
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-start",
            "status": "failed",
            "tasks": [
                {
                    "id": "task-001",
                    "description": "failed",
                    "status": "failed",
                }
            ],
        },
    )
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run-start",
                "task_id": "task-001",
                "event": "model_attempt_started",
                "model": "qwen_coder",
                "attempt": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["model_errors"] == []
    assert diagnostics["failure_class"] == "task_failure"


def test_collect_run_diagnostics_uses_failed_task_not_historical_metrics(tmp_path):
    run_dir = tmp_path / "run-current-task"
    (run_dir / "metrics").mkdir(parents=True)
    _write_json(
        run_dir / "state.json",
        {
            "run_id": "run-current-task",
            "status": "failed",
            "tasks": [
                {
                    "id": "task-001",
                    "description": "earlier edit",
                    "status": "passed",
                },
                {
                    "id": "task-002",
                    "description": "add tests",
                    "status": "failed",
                    "error": "no tests ran in 0.00s",
                    "verification_status": "failed",
                },
            ],
        },
    )
    _write_json(
        run_dir / "metrics" / "task-001.json",
        {
            "task_id": "task-001",
            "operation_failures": [
                {"failure_class": "no_match", "detail": "old attempt"}
            ],
            "verification_classification": "preexisting_failures_only",
        },
    )
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps(
            {
                "run_id": "run-current-task",
                "task_id": "task-002",
                "event": "task_completed",
                "passed": False,
                "detail": "no tests ran in 0.00s",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["failure_class"] == "verification_failure"
    assert diagnostics["verifier"]["classification"] is None
    assert "preexisting_failures_only" not in diagnostics["summary"]
    assert "no tests ran" in diagnostics["summary"]


def test_collect_run_diagnostics_reports_latest_checkpoint_commit(tmp_path):
    run_dir = tmp_path / "run-commits"
    run_dir.mkdir()
    _write_json(
        run_dir / "state.json",
        {"run_id": "run-commits", "status": "passed", "tasks": []},
    )
    (run_dir / "trajectory.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "event": "checkpoint_created",
                    "detail": f"commit={commit}; changed_files=app.py",
                }
            )
            for commit in ("1111111", "2222222")
        )
        + "\n",
        encoding="utf-8",
    )

    diagnostics = collect_run_diagnostics(run_dir)

    assert diagnostics["checkpoint"]["commit"] == "2222222"
