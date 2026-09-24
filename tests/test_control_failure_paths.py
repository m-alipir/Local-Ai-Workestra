from __future__ import annotations

import json
from importlib.metadata import version
import subprocess
import threading
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.control_api import ControlAPI
from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.control_application import ControlApplication
from local_agent_orchestrator.services.plan_runner import run_execution_plan
from local_agent_orchestrator.services.project_registry import ProjectRegistry


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
    )
    (path / ".keep").write_text("\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=path, check=True)


def test_failed_task_blocks_dependents_and_skips_unrelated_tasks(tmp_path):
    _init_repo(tmp_path)
    plan = ExecutionPlan(
        request="failure propagation",
        tasks=[
            PlanTask(id="failed", description="Fail"),
            PlanTask(id="dependent", description="Blocked", depends_on=["failed"]),
            PlanTask(id="unrelated", description="Skipped"),
        ],
    )
    failed_execution = MagicMock(passed=False)
    failed_checkpoint = MagicMock(execution=failed_execution, commit=None)

    with (
        patch(
            "local_agent_orchestrator.services.plan_runner.execute_checkpointed_task",
            return_value=failed_checkpoint,
        ) as executor,
        patch(
            "local_agent_orchestrator.services.plan_runner.finalize_run",
            return_value=MagicMock(analytics_path=None, retrospective_path=None),
        ),
    ):
        result = run_execution_plan(
            plan,
            tmp_path,
            ["pytest", "-q"],
            runs_dir=tmp_path.parent / "runs",
        )

    state_path = result.run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result.passed is False
    assert executor.call_count == 1
    assert [task["status"] for task in state["tasks"]] == [
        TaskStatus.FAILED.value,
        TaskStatus.BLOCKED.value,
        TaskStatus.SKIPPED.value,
    ]
    assert "failed" in state["tasks"][1]["error"]


def test_control_api_returns_structured_errors_from_service_calls():
    class InvalidService:
        def list_projects(self):
            raise ValueError("invalid project request")

    api = ControlAPI(service=InvalidService())
    try:
        status, headers, body = api.handle("GET", "/api/projects", {})
    finally:
        api.close()

    payload = json.loads(body)
    assert status == 400
    assert headers["Content-Type"] == "application/json"
    assert payload == {
        "error": {
            "code": "INVALID_REQUEST",
            "message": "invalid project request",
        }
    }


def test_background_start_failure_does_not_break_control_api():
    class FailingService:
        def __init__(self):
            self.finished = threading.Event()

        def start_run(self, payload):
            self.finished.set()
            raise RuntimeError("engine failed")

        def list_projects(self):
            return []

    service = FailingService()
    api = ControlAPI(service=service, max_workers=1)
    try:
        status, _, body = api.handle(
            "POST",
            "/api/runs",
            {},
            json.dumps({"project_id": "demo", "plan_id": "plan"}).encode(),
        )
        assert status == 202
        assert json.loads(body)["status"] == "accepted"
        assert service.finished.wait(1)

        health_status, _, health_body = api.handle("GET", "/api/health", {})
    finally:
        api.close()

    assert health_status == 200
    assert json.loads(health_body) == {"status": "ok", "version": version("local-agent-orchestrator")}


def test_project_list_exposes_path_field_consumed_by_control_ui(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    app.create_project("Demo", repo, ["pytest", "-q"])
    api = ControlAPI(service=app)
    try:
        status, _, body = api.handle("GET", "/api/projects", {})
    finally:
        api.close()

    assert status == 200
    projects = json.loads(body)
    assert projects[0]["path"] == str(repo.resolve())
