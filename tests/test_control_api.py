from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from datetime import datetime, timedelta, timezone

from local_agent_orchestrator.control_api import (
    ControlAPI,
    create_server,
)
from local_agent_orchestrator.services.control_application import ControlApplication
from local_agent_orchestrator.services.project_registry import ProjectRegistry
from local_agent_orchestrator.models.task import RunState, TaskStatus


class FakeService:
    def __init__(self, runs_dir):
        self.runs_dir = runs_dir
        self.started = threading.Event()
        self.start_payload = None

    def list_projects(self):
        return []

    def start_run(self, payload):
        self.start_payload = payload
        self.started.set()


def request(server, method, path, body=None, headers=None):
    connection = HTTPConnection(*server.server_address)
    encoded = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if encoded is not None:
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, encoded, request_headers)
    response = connection.getresponse()
    content = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), content


def test_health_and_loopback_default(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        status, _, content = request(server, "GET", "/api/health")
        assert status == 200
        assert json.loads(content) == {"status": "ok"}
    finally:
        server.server_close()


def test_non_loopback_binding_is_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        create_server(runs_dir=tmp_path / "runs", host="0.0.0.0", port=0)


def test_root_serves_static_control_ui(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, content = request(server, "GET", "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"Workestra Control" in content
    finally:
        server.shutdown()
        server.server_close()


def test_event_replay_honours_last_event_id(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text(
        json.dumps({"event": "one", "run_id": "run-1", "task_id": "t1"})
        + "\n"
        + json.dumps({"event": "two", "run_id": "run-1", "task_id": "t1"})
        + "\n",
        encoding="utf-8",
    )
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, content = request(
            server,
            "GET",
            "/api/runs/run-1/events",
            headers={"Last-Event-ID": "1"},
        )
        assert status == 200
        assert headers["Content-Type"] == "text/event-stream"
        assert b"id: 2" in content
        assert b'"event": "two"' in content
        assert b'"event": "one"' not in content
    finally:
        server.server_close()


def test_malformed_and_untrusted_requests_are_rejected(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = request(
            server,
            "POST",
            "/api/runs",
            body={"command": "rm -rf /"},
        )
        assert status == 400

        status, _, _ = request(
            server,
            "GET",
            "/api/runs/../etc/passwd/events",
        )
        assert status in {400, 404}

        status, _, _ = request(
            server,
            "GET",
            "/api/runs/run-1/events",
            headers={"Last-Event-ID": "bad"},
        )
        assert status == 400
    finally:
        server.server_close()


def test_start_delegates_to_service_without_engine_copy(tmp_path):
    service = FakeService(tmp_path / "runs")
    server = create_server(service=service, runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = request(
            server,
            "POST",
            "/api/runs",
            body={"plan_id": "plan-1"},
        )
        assert status == 202
        assert service.started.wait(1)
        assert service.start_payload == {"plan_id": "plan-1"}
    finally:
        server.shutdown()
        server.server_close()


def test_unsupported_pause_is_not_reported_as_success(tmp_path):
    server = create_server(runs_dir=tmp_path / "runs", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, content = request(server, "POST", "/api/runs/run-1/pause", {})
        assert status == 501
        assert b"UNSUPPORTED" in content
    finally:
        server.shutdown()
        server.server_close()


def test_missing_application_run_is_not_reported_as_service_failure(tmp_path):
    from local_agent_orchestrator.control_api import ControlAPI

    class Service:
        def get_run(self, run_id):
            raise FileNotFoundError(f"Run not found: {run_id}")

    api = ControlAPI(Service(), runs_dir=tmp_path / "runs")
    try:
        status, _, content = api.handle("GET", "/api/runs/missing", {})
    finally:
        api.close()

    assert status == 404
    assert b"NOT_FOUND" in content


def test_filesystem_service_exposes_structured_run_diagnostics(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": "run-1", "status": "passed", "tasks": []}),
        encoding="utf-8",
    )
    api = ControlAPI(runs_dir=tmp_path / "runs")
    try:
        status, _, content = api.handle("GET", "/api/runs/run-1/diagnostics", {})
    finally:
        api.close()
    assert status == 200
    assert json.loads(content)["failure_class"] == "none"


def test_filesystem_service_accepts_project_scoped_reads(tmp_path):
    run_dir = tmp_path / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps({"run_id": "run-1", "status": "passed", "tasks": []}),
        encoding="utf-8",
    )
    api = ControlAPI(runs_dir=tmp_path / "runs")
    try:
        status, _, content = api.handle(
            "GET", "/api/runs/run-1?project_id=project-1", {}
        )
    finally:
        api.close()
    assert status == 200
    assert json.loads(content)["run_id"] == "run-1"


def test_plan_list_routes_project_filter_to_application_service(tmp_path):
    class Service:
        def list_plans(self, project_id=None):
            return [{"id": "plan-1", "project_id": project_id}]

    api = ControlAPI(Service(), runs_dir=tmp_path / "runs")
    try:
        status, _, content = api.handle(
            "GET", "/api/plans?project_id=project-1", {}
        )
    finally:
        api.close()

    assert status == 200
    assert json.loads(content) == [{"id": "plan-1", "project_id": "project-1"}]


def test_project_update_and_delete_routes_preserve_workspace(tmp_path):
    repo = tmp_path / "repo"
    new_repo = tmp_path / "new-repo"
    repo.mkdir()
    new_repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    api = ControlAPI(app, runs_dir=tmp_path / "runs")
    try:
        status, _, body = api.handle(
            "PATCH",
            f"/api/projects/{project.id}",
            {},
            json.dumps({"test_argv": ["python", "-m", "pytest"]}).encode(),
        )
        assert status == 200
        verifier_only = json.loads(body)
        assert verifier_only["name"] == "Demo"
        assert verifier_only["path"] == str(repo.resolve())
        assert verifier_only["test_command"] == ["python", "-m", "pytest"]

        status, _, body = api.handle(
            "PATCH",
            f"/api/projects/{project.id}",
            {},
            json.dumps({
                "name": "Renamed",
                "path": str(new_repo),
                "test_argv": ["python", "-m", "pytest"],
            }).encode(),
        )
        assert status == 200
        updated = json.loads(body)
        assert updated["name"] == "Renamed"
        assert updated["path"] == str(new_repo.resolve())
        assert updated["test_command"] == ["python", "-m", "pytest"]

        status, _, body = api.handle(
            "DELETE", f"/api/projects/{project.id}", {}, b""
        )
        assert status == 200
        assert json.loads(body)["id"] == project.id
        assert repo.is_dir()
        assert new_repo.is_dir()
        assert app.list_projects() == []
    finally:
        api.close()


def test_project_update_route_rejects_shell_verifier(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    api = ControlAPI(app)
    try:
        status, _, body = api.handle(
            "PUT",
            f"/api/projects/{project.id}",
            {},
            json.dumps({"test_argv": "pytest -q"}).encode(),
        )
    finally:
        api.close()
    assert status == 400
    assert b"test_argv" in body


def test_run_cleanup_route_removes_only_terminal_control_artifact(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = repo / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    run_dir = project.runs_dir / "failed-run"
    run_dir.mkdir(parents=True)
    state = RunState(
        run_id="failed-run",
        request="disposable failure",
        status=TaskStatus.FAILED,
        updated_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    (run_dir / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
    (run_dir / "trajectory.jsonl").write_text("failure\n", encoding="utf-8")
    archived_dir = project.runs_dir / "archived-run"
    archived_dir.mkdir(parents=True)
    (archived_dir / "state.json").write_text(
        state.model_copy(update={"run_id": "archived-run"}).model_dump_json(),
        encoding="utf-8",
    )

    api = ControlAPI(app)
    try:
        status, _, raw = api.handle(
            "POST",
            "/api/runs/archived-run/archive",
            {},
            json.dumps({"project_id": project.id}).encode(),
        )
        result = json.loads(raw)
        assert status == 200 and result["archived"] is True
        assert (project.runs_dir / ".archive" / "archived-run" / "state.json").is_file()

        status, _, body = api.handle(
            "POST",
            "/api/runs/failed-run/cleanup",
            {},
            json.dumps({"project_id": project.id}).encode(),
        )
    finally:
        api.close()

    assert status == 200
    assert json.loads(body) == {"run_id": "failed-run", "deleted": True}
    assert not run_dir.exists()
    assert marker.read_text(encoding="utf-8") == "keep"
