import json
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.core.config import load_models
from local_agent_orchestrator.services.analytics import append_run_analytics
from local_agent_orchestrator.services.retrospective import (
    build_retrospective_context,
    collect_run_metrics,
    generate_retrospective,
)


def _write_run(
    root,
    metrics,
    *,
    status="passed",
    task_status="passed",
    events=(),
):
    (root / "metrics").mkdir()
    (root / "metrics" / "task-001.json").write_text(
        json.dumps(metrics),
    )
    (root / "state.json").write_text(json.dumps({
        "status": status,
        "tasks": [{"id": "task-001", "status": task_status}],
    }))
    (root / "trajectory.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
    )


def _metrics(**overrides):
    values = {
        "task_id": "task-001",
        "description": "Implement feature",
        "attempts": 1,
        "passed": True,
        "changed_files": ["app.py"],
        "test_returncode": 0,
        "commit": "abc123",
        "qwen_attempts": 1,
        "devstral_used": False,
        "accepted_model": "qwen_coder",
        "accepted_attempt": 1,
        "operation_failures": [],
        "baseline_returncode": 0,
        "baseline_passed": True,
        "baseline_failure_identities": [],
        "post_change_failure_identities": [],
        "verification_classification": "passed",
        "diagnoses": [],
    }
    values.update(overrides)
    return values


def _fake_reviewer(content="RECOMMENDATION:\nNo change."):
    fake = MagicMock()
    fake.run.return_value.content = content
    return fake


def test_collect_run_metrics(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    (metrics_dir / "task-001.json").write_text(
        json.dumps({
            "task_id": "task-001",
            "attempts": 2,
        })
    )

    result = collect_run_metrics(tmp_path)

    assert result[0]["task_id"] == "task-001"
    assert result[0]["attempts"] == 2


def test_generate_retrospective(tmp_path):
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    (metrics_dir / "task-001.json").write_text(
        json.dumps({
            "task_id": "task-001",
            "attempts": 1,
            "passed": True,
        })
    )

    fake = MagicMock()
    fake.run.return_value.content = (
        "STRONG:\nTests passed.\n"
        "WEAK:\nNone.\n"
        "WASTE:\nNone.\n"
        "RECOMMENDATION:\nKeep current routing.\n"
        "REASONING_ADJUSTMENT:\nNo change."
    )

    with patch(
        "local_agent_orchestrator.services.retrospective.NemotronRetrospective",
        return_value=fake,
    ) as retrospective_class:
        path = generate_retrospective(tmp_path)

    assert path.exists()
    assert "STRONG:" in path.read_text()
    assert retrospective_class.call_args.kwargs["model"] == load_models().models["bonsai2"]


def test_successful_clean_run_does_not_invent_failure(tmp_path):
    _write_run(
        tmp_path,
        _metrics(),
        events=[{
            "event": "checkpoint_created",
            "model": "qwen_coder",
            "attempt": 1,
            "passed": True,
            "detail": "commit=abc123; changed_files=app.py",
        }],
    )
    fake = _fake_reviewer("RECOMMENDATION:\nNo change.")

    with patch(
        "local_agent_orchestrator.services.retrospective.NemotronRetrospective",
        return_value=fake,
    ):
        output = generate_retrospective(tmp_path).read_text()

    assert "AUTHORITATIVE FACTS:" in output
    assert "OBSERVED FAILURE:\nNone recorded." in output
    assert "SUGGESTION:\ntask-001: no corrective action recorded." in output


def test_preexisting_baseline_failure_is_marked_as_repository_debt(tmp_path):
    failure = "tests/test_admin.py::test_scheduler"
    _write_run(
        tmp_path,
        _metrics(
            passed=True,
            test_returncode=1,
            baseline_returncode=1,
            baseline_passed=False,
            baseline_failure_identities=[failure],
            post_change_failure_identities=[failure],
            verification_classification="preexisting_failures_only",
        ),
    )
    fake = _fake_reviewer(
        "RECOMMENDATION:\nInvestigate the scheduler failure as part of this task."
    )

    with patch(
        "local_agent_orchestrator.services.retrospective.NemotronRetrospective",
        return_value=fake,
    ):
        output = generate_retrospective(tmp_path).read_text()

    assert "pre-existing baseline failure" in output
    suggestion = output.split("SUGGESTION:\n", 1)[1]
    assert "unrelated pre-existing repository debt" in suggestion
    assert "agent-caused" not in suggestion


def test_failed_operation_class_is_the_observed_failure(tmp_path):
    _write_run(
        tmp_path,
        _metrics(
            passed=False,
            attempts=2,
            operation_failures=[{
                "model": "qwen_coder",
                "attempt": 1,
                "failure_class": "no_match",
                "detail": "app.py",
            }],
        ),
        status="failed",
        task_status="failed",
        events=[{
            "event": "coding_output_rejected",
            "model": "qwen_coder",
            "attempt": 1,
            "passed": False,
            "failure_class": "no_match",
            "detail": "Exact replacement matched zero times: app.py",
        }],
    )
    fake = _fake_reviewer("RECOMMENDATION:\nUse a different model.")

    with patch(
        "local_agent_orchestrator.services.retrospective.NemotronRetrospective",
        return_value=fake,
    ):
        output = generate_retrospective(tmp_path).read_text()

    assert "no_match" in output
    assert "failure class" in output


def test_reviewer_hallucination_cannot_override_baseline_attribution(tmp_path):
    failure = "tests/test_admin.py::test_scheduler"
    metrics = _metrics(
        test_returncode=1,
        baseline_returncode=1,
        baseline_passed=False,
        baseline_failure_identities=[failure],
        post_change_failure_identities=[failure],
        verification_classification="preexisting_failures_only",
        diagnoses=["The agent introduced the scheduler failure."],
    )
    _write_run(tmp_path, metrics)
    context = build_retrospective_context(tmp_path)

    assert context["authoritative_facts"]["tasks"][0]["failure_attribution"] == (
        "pre-existing repository debt; not agent-caused"
    )
    assert context["lower_authority_commentary"]["reviewer_diagnoses"] == [
        "The agent introduced the scheduler failure."
    ]


def test_checkpoint_failure_is_reported_as_checkpoint_failure(tmp_path):
    _write_run(
        tmp_path,
        _metrics(
            passed=False,
            commit=None,
        ),
        status="failed",
        task_status="failed",
        events=[{
            "event": "checkpoint_failed",
            "passed": False,
            "detail": "Checkpoint failed: hook failed",
        }],
    )
    fake = _fake_reviewer("RECOMMENDATION:\nRetry the commit.")

    with patch(
        "local_agent_orchestrator.services.retrospective.NemotronRetrospective",
        return_value=fake,
    ):
        output = generate_retrospective(tmp_path).read_text()

    assert "checkpoint_failed" in output
    assert "checkpoint failure" in output.lower()


def test_failed_attempt_does_not_claim_edits_survived_rollback(tmp_path):
    _write_run(
        tmp_path,
        _metrics(
            attempts=2,
            accepted_attempt=2,
            operation_failures=[{
                "model": "qwen_coder",
                "attempt": 1,
                "failure_class": "no_op",
                "detail": "no workspace changes",
            }],
        ),
        events=[{
            "event": "coding_output_rejected",
            "attempt": 1,
            "failure_class": "no_op",
            "detail": "no workspace changes",
        }, {
            "event": "checkpoint_created",
            "attempt": 2,
            "passed": True,
            "detail": "commit=abc123; changed_files=app.py",
        }],
    )
    context = build_retrospective_context(tmp_path)
    task = context["authoritative_facts"]["tasks"][0]

    assert task["accepted_attempt"] == 2
    assert "survived" not in json.dumps(task)


def test_unknown_repository_condition_stays_unknown(tmp_path):
    _write_run(
        tmp_path,
        _metrics(
            baseline_returncode=None,
            baseline_passed=None,
            verification_classification=None,
            commit=None,
        ),
        status="failed",
        task_status="failed",
    )
    context = build_retrospective_context(tmp_path)

    task = context["authoritative_facts"]["tasks"][0]
    assert task["failure_attribution"] == "unknown; not recorded"
    assert "task-001.verification_classification" in context["unknown"]


def test_malformed_state_tasks_stay_unknown(tmp_path):
    _write_run(tmp_path, _metrics())
    (tmp_path / "state.json").write_text(json.dumps({
        "status": "passed",
        "tasks": "not-a-task-list",
    }))

    context = build_retrospective_context(tmp_path)

    task = context["authoritative_facts"]["tasks"][0]
    assert task["task_status"] == "unknown"
    assert "run.tasks" in context["unknown"]


def test_first_attempt_qwen_success_is_explicitly_recorded(tmp_path):
    _write_run(tmp_path, _metrics())
    context = build_retrospective_context(tmp_path)
    task = context["authoritative_facts"]["tasks"][0]

    assert task["accepted_model"] == "qwen_coder"
    assert task["accepted_attempt"] == 1
    assert task["operation_failures"] == []


def test_append_run_analytics(tmp_path):
    path = append_run_analytics(
        run_id="run123",
        metrics=[{"task_id": "task-001"}],
        analytics_dir=tmp_path,
    )

    assert path.exists()
    assert "run123" in path.read_text()
