import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.models.plan_intake import PlanIntakeResult
from local_agent_orchestrator.models.task import RunState, TaskStatus
from local_agent_orchestrator.services.control_application import (
    ControlApplication,
)
from local_agent_orchestrator.services.project_registry import ProjectRegistry


def test_project_registry_persists_projects_and_rejects_shell_strings(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")
    (tmp_path / "repo").mkdir()
    project = registry.register(
        "Demo",
        tmp_path / "repo",
        ["pytest", "-q"],
    )

    restored = ProjectRegistry(tmp_path / "projects.json").get(project.id)

    assert restored == project
    assert restored.test_command == ("pytest", "-q")
    assert project.runs_dir.is_relative_to(tmp_path)
    assert not project.runs_dir.is_relative_to(tmp_path / "repo")
    assert not project.analytics_dir.is_relative_to(tmp_path / "repo")

    with pytest.raises(ValueError, match="sequence"):
        registry.register("Shell", tmp_path / "repo", "pytest -q")


def test_application_starts_with_trusted_project_verifier(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest", "-q"])
    plan = ExecutionPlan(
        request="Do work",
        tasks=[
            PlanTask(
                description="Run the requested work",
                verification=["rm", "-rf", "/"],
            )
        ],
    )
    result = MagicMock(run_id="run123")

    with patch(
        "local_agent_orchestrator.services.control_application.run_execution_plan",
        return_value=result,
    ) as runner:
        assert app.start_run(project.id, plan) is result

    assert runner.call_args.kwargs["workspace_root"] == repo.resolve()
    assert runner.call_args.kwargs["test_command"] == ["pytest", "-q"]
    assert runner.call_args.kwargs["plan"] is plan
    assert runner.call_args.kwargs["runs_dir"] == project.runs_dir
    assert runner.call_args.kwargs["analytics_dir"] == project.analytics_dir


def test_application_lifecycle_delegates_and_reads_artifacts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest", "-q"])
    run_dir = project.runs_dir / "run123"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            RunState(
                run_id="run123",
                request="Do work",
                status=TaskStatus.WAITING_FOR_APPROVAL,
            ).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    (run_dir / "trajectory.jsonl").write_text("event\n", encoding="utf-8")
    (run_dir / "plan.json").write_text("{}\n", encoding="utf-8")

    state = app.get_run("run123")
    assert state.status == TaskStatus.WAITING_FOR_APPROVAL
    assert [item.run_id for item in app.list_runs()] == ["run123"]
    assert app.list_artifacts("run123") == ("plan.json", "state.json", "trajectory.jsonl")
    assert app.read_artifacts("run123")[-1] == {
        "name": "trajectory.jsonl",
        "size": len("event\n"),
    }
    assert app.read_artifact("run123", "trajectory.jsonl") == "event\n"

    with (
        patch(
            "local_agent_orchestrator.services.control_application.approve_waiting_task",
            return_value="task-001",
        ) as approve,
        patch(
            "local_agent_orchestrator.services.control_application.resume_execution_plan",
            return_value=MagicMock(run_id="run123"),
        ) as resume,
    ):
        assert app.approve_run("run123", task_id="task-001") == "task-001"
        assert app.resume_run("run123").run_id == "run123"

    approve.assert_called_once_with(
        run_id="run123",
        runs_dir=project.runs_dir,
        task_id="task-001",
    )
    assert resume.call_args.kwargs["run_id"] == "run123"
    assert resume.call_args.kwargs["workspace_root"] == repo.resolve()
    assert resume.call_args.kwargs["test_command"] == ["pytest", "-q"]


def test_events_are_replayed_from_durable_trajectory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    run_dir = project.runs_dir / "run123"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        RunState(run_id="run123", request="Do work").model_dump_json(),
        encoding="utf-8",
    )
    (run_dir / "trajectory.jsonl").write_text(
        '{"event":"one"}\n{"event":"two"}\n',
        encoding="utf-8",
    )

    assert app.read_events("run123", after_id=1) == [
        {"event": "two", "id": 2}
    ]

    with pytest.raises(FileNotFoundError, match="Run not found"):
        app.read_events("missing")


def test_artifact_reads_reject_paths_outside_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    run_dir = project.runs_dir / "run123"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        RunState(run_id="run123", request="Do work").model_dump_json(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes"):
        app.read_artifact("run123", "../state.json")


def test_plan_import_compile_and_start_use_durable_compiled_plan(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest", "-q"])

    imported = app.import_plan({
        "project_id": project.id,
        "markdown": "# Rough plan\n\nAdd a feature.\n",
    })
    assert imported["project_id"] == project.id
    assert (tmp_path / "plans" / f"{imported['id']}.md").is_file()

    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(
            request="Add a feature",
            tasks=[PlanTask(description="Implement it")],
        ),
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ):
        assert app.compile_plan(str(imported["id"])).status == "compiled"

    with patch(
        "local_agent_orchestrator.services.control_application.run_execution_plan",
        return_value=MagicMock(run_id="run-1"),
    ) as runner:
        app.start_plan_run(project.id, str(imported["id"]))

    assert runner.call_args.kwargs["plan"].request == "Add a feature"


def test_plan_record_cannot_read_markdown_outside_control_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    imported = app.import_plan({
        "project_id": project.id,
        "markdown": "# Safe",
    })
    record = tmp_path / "plans" / f"{imported['id']}.record.json"
    values = json.loads(record.read_text(encoding="utf-8"))
    values["markdown_path"] = str(tmp_path / "outside.md")
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    record.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes"):
        app.compile_plan(str(imported["id"]))


def test_read_diff_derives_committed_diff_from_authoritative_metrics(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.name", "Test"), ("config", "user.email", "test@example.invalid")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    source = repo / "file.txt"
    source.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    source.write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    run_dir = project.runs_dir / "run123"
    (run_dir / "metrics").mkdir(parents=True)
    (run_dir / "state.json").write_text(
        RunState(run_id="run123", request="Do work").model_dump_json(),
        encoding="utf-8",
    )
    (run_dir / "metrics" / "task-001.json").write_text(
        json.dumps({"commit": commit}),
        encoding="utf-8",
    )

    diff = app.read_diff("run123")
    assert "-before" in diff["content"]
    assert "+after" in diff["content"]
