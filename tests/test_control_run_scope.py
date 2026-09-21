from __future__ import annotations

import json

from local_agent_orchestrator.control_api import ControlAPI
from local_agent_orchestrator.models.task import RunState, TaskState, TaskStatus
from local_agent_orchestrator.services.control_application import ControlApplication
from local_agent_orchestrator.services.project_registry import ProjectRegistry


def _write_run(project, run_id: str, status: TaskStatus, event: str):
    run_dir = project.runs_dir / run_id
    run_dir.mkdir(parents=True)
    state = RunState(
        run_id=run_id,
        request="run request",
        status=status,
        current_task="task-001" if status == TaskStatus.FAILED else None,
        tasks=[
            TaskState(
                id="task-001",
                description="task",
                status=status,
                error="verification failed" if status == TaskStatus.FAILED else None,
            )
        ],
    )
    (run_dir / "state.json").write_text(
        state.model_dump_json(),
        encoding="utf-8",
    )
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"event": event, "run_id": run_id, "task_id": "task-001"}) + "\n",
        encoding="utf-8",
    )


def test_run_list_detail_and_diagnostics_report_the_same_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    _write_run(project, "run-1", TaskStatus.FAILED, "failed-in-project")
    api = ControlAPI(service=app)

    try:
        list_status, _, list_body = api.handle(
            "GET",
            f"/api/runs?project_id={project.id}",
            {},
        )
        detail_status, _, detail_body = api.handle(
            "GET",
            f"/api/runs/run-1?project_id={project.id}",
            {},
        )
        diagnostics_status, _, diagnostics_body = api.handle(
            "GET",
            f"/api/runs/run-1/diagnostics?project_id={project.id}",
            {},
        )
    finally:
        api.close()

    listed = json.loads(list_body)
    detail = json.loads(detail_body)
    diagnostics = json.loads(diagnostics_body)
    assert list_status == detail_status == diagnostics_status == 200
    assert listed[0]["run_id"] == detail["run_id"] == diagnostics["run_id"] == "run-1"
    assert listed[0]["status"] == detail["status"] == "failed"
    assert diagnostics["failing_task"]["id"] == "task-001"


def test_run_detail_diagnostics_and_sse_are_scoped_to_selected_project(tmp_path):
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    first_repo.mkdir()
    second_repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    first = app.create_project("First", first_repo, ["pytest"])
    second = app.create_project("Second", second_repo, ["pytest"])
    _write_run(first, "same-run", TaskStatus.FAILED, "first-event")
    _write_run(second, "same-run", TaskStatus.PASSED, "second-event")
    api = ControlAPI(service=app)

    try:
        detail_status, _, detail_body = api.handle(
            "GET",
            f"/api/runs/same-run?project_id={first.id}",
            {},
        )
        diagnostics_status, _, diagnostics_body = api.handle(
            "GET",
            f"/api/runs/same-run/diagnostics?project_id={first.id}",
            {},
        )
        events_status, _, events_body = api.handle(
            "GET",
            f"/api/runs/same-run/events?project_id={first.id}",
            {},
        )
    finally:
        api.close()

    assert detail_status == diagnostics_status == events_status == 200
    assert json.loads(detail_body)["status"] == "failed"
    assert json.loads(diagnostics_body)["failure_class"] == "task_failure"
    assert b"first-event" in events_body
    assert b"second-event" not in events_body


def test_sse_ignores_events_labeled_for_another_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    _write_run(project, "run-1", TaskStatus.PASSED, "selected")
    (project.runs_dir / "run-1" / "trajectory.jsonl").write_text(
        json.dumps({"event": "selected", "run_id": "run-1"})
        + "\n"
        + json.dumps({"event": "foreign", "run_id": "run-2"})
        + "\n",
        encoding="utf-8",
    )

    events = app.read_events("run-1", project_id=project.id)

    assert [event["event"] for event in events] == ["selected"]


def test_artifacts_and_diff_routes_forward_project_scope(tmp_path):
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    first_repo.mkdir()
    second_repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    first = app.create_project("First", first_repo, ["pytest"])
    second = app.create_project("Second", second_repo, ["pytest"])
    _write_run(first, "same-run", TaskStatus.FAILED, "first-event")
    _write_run(second, "same-run", TaskStatus.PASSED, "second-event")
    (first.runs_dir / "same-run" / "first.diff").write_text("first", encoding="utf-8")
    (second.runs_dir / "same-run" / "second.diff").write_text("second", encoding="utf-8")
    api = ControlAPI(service=app)

    try:
        artifacts_status, _, artifacts_body = api.handle(
            "GET",
            f"/api/runs/same-run/artifacts?project_id={first.id}",
            {},
        )
        diff_status, _, diff_body = api.handle(
            "GET",
            f"/api/runs/same-run/diff?project_id={first.id}",
            {},
        )
    finally:
        api.close()

    assert artifacts_status == diff_status == 200
    assert "first.diff" in {item["name"] for item in json.loads(artifacts_body)}
    assert "second.diff" not in {item["name"] for item in json.loads(artifacts_body)}
    assert json.loads(diff_body)["content"] == "first"
