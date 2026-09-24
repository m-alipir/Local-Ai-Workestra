import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.models.plan import ExecutionPlan, PlanTask
from local_agent_orchestrator.models.plan_intake import PlanIntakeResult
from local_agent_orchestrator.models.project_spec import ProjectSpec
from local_agent_orchestrator.models.task import RunState, TaskStatus
from local_agent_orchestrator.control_api.server import ControlAPI
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


def test_project_registry_rejects_duplicate_canonical_workspace_paths(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")
    repo = tmp_path / "repo"
    repo.mkdir()
    registry.register("Original", repo, ["pytest"], project_id="original")

    with pytest.raises(ValueError, match="Project workspace path is already registered"):
        registry.register("Alias", tmp_path / "nested" / ".." / "repo", ["pytest"], project_id="alias")


def test_existing_project_registration_uses_trusted_verifier_by_default(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))

    project = app.create_project_request({
        "name": "Existing",
        "path": str(repo),
    })

    assert project.test_command == ("uv", "run", "pytest", "-q")


def test_project_update_preserves_control_history_and_validates_verifier(tmp_path):
    repo = tmp_path / "repo"
    new_repo = tmp_path / "new-repo"
    repo.mkdir()
    new_repo.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")
    project = registry.register("Demo", repo, ["pytest", "-q"])
    history = project.runs_dir / "run-1" / "state.json"
    history.parent.mkdir(parents=True)
    history.write_text("{}", encoding="utf-8")

    updated = registry.update(
        project.id,
        name="Renamed",
        workspace_root=new_repo,
        test_command=["python", "-m", "pytest"],
    )

    assert updated.name == "Renamed"
    assert updated.workspace_root == new_repo.resolve()
    assert updated.test_command == ("python", "-m", "pytest")
    assert updated.runs_dir == project.runs_dir
    assert history.is_file()
    assert repo.is_dir()
    with pytest.raises(ValueError, match="sequence"):
        registry.update(project.id, test_command="pytest -q")
    with pytest.raises(ValueError, match="not a directory"):
        registry.update(project.id, workspace_root=tmp_path / "missing")


def test_partial_project_update_merges_and_validates_final_configuration(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest", "-q"])

    updated = app.update_project_request(
        project.id,
        {"test_argv": ["python", "-m", "pytest"]},
    )

    assert updated.name == "Demo"
    assert updated.workspace_root == repo.resolve()
    assert updated.test_command == ("python", "-m", "pytest")
    renamed = app.update_project_request(project.id, {"name": "Renamed"})
    assert renamed.name == "Renamed"
    assert renamed.workspace_root == repo.resolve()
    assert renamed.test_command == ("python", "-m", "pytest")
    with pytest.raises(ValueError, match="non-empty argv"):
        app.update_project_request(project.id, {"test_argv": []})
    with pytest.raises(ValueError, match="cannot be empty"):
        app.update_project_request(project.id, {"path": ""})


def test_delete_project_removes_only_registry_entry(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "projects.json"
    app = ControlApplication(ProjectRegistry(registry_path))
    project = app.create_project("Demo", repo, ["pytest"])
    imported = app.import_plan({"project_id": project.id, "markdown": "# Keep"})
    history = project.runs_dir / "run-1" / "state.json"
    history.parent.mkdir(parents=True)
    history.write_text("{}", encoding="utf-8")

    deleted = app.delete_project(project.id)

    assert deleted.id == project.id
    assert app.list_projects() == []
    assert repo.is_dir()
    assert history.is_file()
    assert (tmp_path / "plans" / f"{imported['id']}.record.json").is_file()


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
    ) as runner, patch(
        "local_agent_orchestrator.services.control_application.assert_verification_environment_supported",
    ):
        app.start_plan_run(project.id, str(imported["id"]), 1)

    assert runner.call_args.kwargs["plan"].request == "Add a feature"


def test_compiled_project_spec_is_persisted_with_immutable_revision(tmp_path):
    registry_path = tmp_path / "projects.json"
    app = ControlApplication(ProjectRegistry(registry_path))
    imported = app.import_plan({"markdown": "# Bookmarks API\nBuild it."})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Build it", tasks=[PlanTask(description="Implement it")]),
        project_spec=ProjectSpec(
            name="Bookmarks API",
            slug="bookmarks-api",
            intent="new",
            workspace_root="projects/bookmarks-api",
            capabilities=["python", "fastapi", "pytest"],
            bootstrap_profile="fastapi",
            verifier=["uv", "run", "pytest", "-q"],
        ),
    )

    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ):
        result = app.compile_plan(str(imported["id"]))

    assert result.project_spec == compiled.project_spec
    restored = ControlApplication(ProjectRegistry(registry_path)).compile_plan(str(imported["id"]))
    assert restored.project_spec == compiled.project_spec
    revision = json.loads(
        (tmp_path / "plans" / f"{imported['id']}.revisions" / "1.json").read_text()
    )
    assert revision["project_spec"]["slug"] == "bookmarks-api"
    assert revision["project_spec_digest"]


def test_research_project_spec_remains_visible_after_rejected_compile(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Bookmarks Web\nBuild it."})
    spec = ProjectSpec(
        name="Bookmarks Web",
        slug="bookmarks-web",
        intent="new",
        workspace_root="projects/bookmarks-web",
        capabilities=["node", "typescript", "react"],
        research_requirements=[
            {"topic": "Node bootstrap", "reason": "No trusted profile"},
        ],
    )
    rejected = PlanIntakeResult(
        status="rejected",
        project_spec=spec,
        unresolved_issues=["Research required: Node bootstrap — No trusted profile"],
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=rejected,
    ):
        app.compile_plan(str(imported["id"]))

    stored = app.get_plan(str(imported["id"]))
    assert stored["status"] == "rejected"
    assert stored["project_spec"]["slug"] == "bookmarks-web"


def test_compiled_greenfield_plan_can_be_created_then_started_from_same_revision(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Bookmarks API\nBuild it."})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Build it", tasks=[PlanTask(description="Implement it")]),
        project_spec=ProjectSpec(
            name="Bookmarks API",
            slug="bookmarks-api",
            intent="new",
            workspace_root="projects/bookmarks-api",
            capabilities=["python", "fastapi", "pytest"],
            bootstrap_profile="fastapi",
            verifier=["uv", "run", "pytest", "-q"],
        ),
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ):
        app.compile_plan(str(imported["id"]))

    eligibility = app.project_creation_eligibility(str(imported["id"]), 1)
    assert eligibility["eligible"] is True
    assert eligibility["reasons"] == []
    target = tmp_path / "projects" / "bookmarks-api"
    assert not target.exists()
    stale = app.project_creation_eligibility(str(imported["id"]), 2)
    assert stale["eligible"] is False
    assert stale["reasons"] == ["Plan revision is stale; reload the compiled plan before creating a project."]
    assert not target.exists()

    with (
        patch(
            "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ),
        patch("local_agent_orchestrator.services.control_application.assert_verification_environment_supported"),
        patch(
            "local_agent_orchestrator.services.control_application.run_execution_plan",
            return_value=MagicMock(run_id="run-1"),
        ) as runner,
    ):
        project = app.create_project_from_plan(str(imported["id"]), 1)
        retried_project = app.create_project_from_plan(str(imported["id"]), 1)
        assert retried_project == project
        assert [item.id for item in app.list_projects()] == [project.id]
        assert app.get_plan(str(imported["id"]))["project_id"] == project.id
        app.start_run_request({
            "project_id": project.id,
            "plan_id": imported["id"],
            "compiled_revision": 1,
        })

    target = target.resolve()
    assert target.is_dir()
    assert (target / "pyproject.toml").is_file()
    assert runner.call_args.kwargs["workspace_root"] == target


def test_failed_greenfield_bootstrap_does_not_register_or_bind_project(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Bookmarks API\nBuild it."})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Build it", tasks=[PlanTask(description="Implement it")]),
        project_spec=ProjectSpec(
            name="Bookmarks API",
            slug="bookmarks-api",
            intent="new",
            workspace_root="projects/bookmarks-api",
            capabilities=["python", "fastapi", "pytest"],
            bootstrap_profile="fastapi",
            verifier=["uv", "run", "pytest", "-q"],
        ),
    )
    with patch("local_agent_orchestrator.services.control_application.compile_markdown_plan", return_value=compiled):
        app.compile_plan(str(imported["id"]))

    with (
        patch(
            "local_agent_orchestrator.services.project_bootstrap.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["uv", "lock"], stderr="lock failed"),
        ),
        patch("local_agent_orchestrator.services.control_application.run_execution_plan") as runner,
    ):
        with pytest.raises(RuntimeError, match="trusted bootstrap command failed"):
            app.create_project_from_plan(str(imported["id"]), 1)
        runner.assert_not_called()

    assert app.list_projects() == []
    assert app.get_plan(str(imported["id"]))["project_id"] is None
    assert not (tmp_path / "projects" / "bookmarks-api").exists()


def test_project_creation_eligibility_reports_blocking_research(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Bookmarks Web\nBuild it."})
    rejected = PlanIntakeResult(
        status="rejected",
        project_spec=ProjectSpec(
            name="Bookmarks Web",
            slug="bookmarks-web",
            intent="new",
            workspace_root="projects/bookmarks-web",
            research_requirements=[{"topic": "Node bootstrap", "reason": "No trusted profile"}],
        ),
        unresolved_issues=["Research required: Node bootstrap — No trusted profile"],
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=rejected,
    ):
        app.compile_plan(str(imported["id"]))

    eligibility = app.project_creation_eligibility(str(imported["id"]), 1)
    assert eligibility["eligible"] is False
    assert eligibility["reasons"] == ["Research required: Node bootstrap — No trusted profile"]


def test_forced_compile_creates_immutable_revision_and_rejects_stale_start(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["pytest"])
    imported = app.import_plan({"project_id": project.id, "markdown": "# Plan"})
    first = PlanIntakeResult(status="compiled", plan=ExecutionPlan(request="first", tasks=[PlanTask(description="first")]))
    second = PlanIntakeResult(status="compiled", plan=ExecutionPlan(request="second", tasks=[PlanTask(description="second")]))
    with patch("local_agent_orchestrator.services.control_application.compile_markdown_plan", side_effect=[first, second]):
        initial = app.compile_plan(str(imported["id"]))
        forced = app.compile_plan(str(imported["id"]), {"force": True})
    assert initial.compiled_revision == 1
    assert forced.compiled_revision == 2
    assert initial.compiled_digest != forced.compiled_digest
    with pytest.raises(RuntimeError, match="stale"):
        app.assert_start_run_allowed({"project_id": project.id, "plan_id": imported["id"], "compiled_revision": 1})


def test_rejected_recompile_preserves_active_compiled_revision_and_history(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Plan"})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Plan", tasks=[PlanTask(description="Implement it")]),
    )
    rejected = PlanIntakeResult(
        status="rejected",
        unresolved_issues=["Research required: exact toolchain"],
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        side_effect=[compiled, rejected],
    ):
        first = app.compile_plan(imported["id"])
        second = app.compile_plan(imported["id"], {"force": True})

    stored = app.get_plan(imported["id"])
    assert first.compiled_revision == 1
    assert second.status == "rejected"
    assert second.compiled_revision is None
    assert stored["status"] == "compiled"
    assert stored["compiled"] is True
    assert stored["compiled_revision"] == 1
    assert stored["last_compile_attempt"]["status"] == "rejected"
    assert (tmp_path / "plans" / f"{imported['id']}.revisions" / "1.json").is_file()


def test_start_rejects_unbootstrappable_project_before_execution(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    project = app.create_project("Demo", repo, ["uv", "run", "pytest", "-q"])
    imported = app.import_plan({"project_id": project.id, "markdown": "# Plan"})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Plan", tasks=[PlanTask(description="Implement it")]),
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ):
        app.compile_plan(str(imported["id"]))

    with pytest.raises(RuntimeError, match=r"missing_metadata"):
        app.assert_start_run_allowed({
            "project_id": project.id,
            "plan_id": imported["id"],
            "compiled_revision": 1,
        })

    assert list(repo.iterdir()) == []


def test_bootstrap_request_accepts_only_bounded_fields(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    with pytest.raises(ValueError, match="Only name"):
        app.bootstrap_python_project_request({"name": "Demo", "path": str(tmp_path / "repo"), "test_argv": ["sh"]})
    with pytest.raises(ValueError, match="profile"):
        app.bootstrap_python_project_request({"name": "Demo", "path": str(tmp_path / "repo"), "profile": 1})


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


def test_compiled_plan_metadata_reuses_durable_result_after_restart(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "projects.json"
    project = ProjectRegistry(registry_path).register("Demo", repo, ["pytest"])
    app = ControlApplication(ProjectRegistry(registry_path))
    imported = app.import_plan({
        "project_id": project.id,
        "markdown": "# Durable plan\n\nAdd the feature.\n",
    })
    compiled = PlanIntakeResult(
        status="compiled",
        assumptions=["The existing module is the integration point."],
        plan=ExecutionPlan(
            request="Add the feature",
            tasks=[PlanTask(description="Implement the feature")],
        ),
    )

    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ) as compiler:
        result = app.compile_plan(str(imported["id"]))
        assert result.plan == compiled.plan
        assert result.compiled_revision == 1

    record = json.loads(
        (tmp_path / "plans" / f"{imported['id']}.record.json").read_text()
    )
    assert record["status"] == "compiled"
    assert record["assumptions"] == compiled.assumptions
    assert record["unresolved_issues"] == []
    assert record["error"] is None
    assert record["compiled_path"] == str(tmp_path / "plans" / f"{imported['id']}.revisions" / "1.json")
    assert record["compiled_digest"]

    restarted = ControlApplication(ProjectRegistry(registry_path))
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        side_effect=AssertionError("durable compiled plan should be reused"),
    ):
        restored = restarted.compile_plan(str(imported["id"]))

    assert restored.status == "compiled"
    assert restored.assumptions == compiled.assumptions
    assert restored.plan == compiled.plan
    assert compiler.call_count == 1
    listed = restarted.list_plans(project.id)
    assert listed[0]["id"] == imported["id"]
    assert listed[0]["status"] == "compiled"
    assert listed[0]["markdown"] == "# Durable plan\n\nAdd the feature.\n"
    assert listed[0]["plan"] == compiled.plan.model_dump(mode="json")


def test_legacy_scope_revision_is_invalidated_without_breaking_plans_view(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Legacy plan\n\nBuild it.\n"})
    plan_id = str(imported["id"])
    old_plan = {
        "request": "Build it",
        "tasks": [{
            "id": "implement",
            "description": "Implement it",
            "kind": "code",
            "depends_on": [],
            "verification": [],
            "file_boundaries": ["app/"],
            "requires_approval": False,
            "risk": "low",
        }],
    }
    old_plan_text = json.dumps(old_plan, indent=2) + "\n"
    revision_path = tmp_path / "plans" / f"{plan_id}.revisions" / "1.json"
    revision_path.parent.mkdir(parents=True)
    revision = {
        "plan_id": plan_id,
        "revision": 1,
        "compiled_at": "2026-09-23T00:00:00+00:00",
        "source_digest": app._digest("# Legacy plan\n\nBuild it.\n"),
        "plan_digest": app._digest(old_plan_text),
        "plan": old_plan,
    }
    revision_path.write_text(json.dumps(revision, indent=2) + "\n")
    record_path = tmp_path / "plans" / f"{plan_id}.record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update({
        "status": "compiled",
        "compiled_path": str(revision_path),
        "compiled_revision": 1,
        "compiled_digest": revision["plan_digest"],
        "source_digest": revision["source_digest"],
        "compiled_at": revision["compiled_at"],
    })
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    original_revision = revision_path.read_text(encoding="utf-8")

    api = ControlAPI(app)
    try:
        status, _, body = api.handle("GET", "/api/plans", {}, b"")
    finally:
        api.close()

    assert status == 200
    listed = json.loads(body)
    assert listed[0]["status"] == "needs_recompile"
    assert listed[0]["compiled"] is False
    assert listed[0]["error"] == (
        f"Stored compiled plan revision {plan_id}/1 is incompatible; recompile required."
    )
    assert listed[0]["markdown"] == "# Legacy plan\n\nBuild it.\n"
    assert revision_path.read_text(encoding="utf-8") == original_revision

    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(
            request="Build it",
            tasks=[PlanTask(description="Implement it", primary_scope=["app/"])],
        ),
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=compiled,
    ):
        result = app.compile_plan(plan_id)

    assert result.status == "compiled"
    assert result.compiled_revision == 2
    assert revision_path.read_text(encoding="utf-8") == original_revision
    assert (tmp_path / "plans" / f"{plan_id}.revisions" / "2.json").is_file()


def test_plan_compile_failure_metadata_persists_and_force_recompiles(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "projects.json"
    app = ControlApplication(ProjectRegistry(registry_path))
    project = app.create_project("Demo", repo, ["pytest"])
    imported = app.import_plan({"project_id": project.id, "markdown": "# Plan"})
    failed = PlanIntakeResult(
        status="failed",
        assumptions=["The target module exists."],
        unresolved_issues=["The acceptance condition is ambiguous."],
        error="compiler unavailable",
    )
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(
            request="Plan",
            tasks=[PlanTask(description="Implement the plan")],
        ),
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        side_effect=[failed, compiled],
    ) as compiler:
        assert app.compile_plan(str(imported["id"])) == failed
        result = app.compile_plan(str(imported["id"]), {"force": True})
        assert result.plan == compiled.plan
        assert result.compiled_revision == 1

    restored = ControlApplication(ProjectRegistry(registry_path)).get_plan(
        str(imported["id"])
    )
    assert restored["status"] == "compiled"
    assert restored["assumptions"] == []
    assert restored["unresolved_issues"] == []
    assert restored["error"] is None
    assert compiler.call_count == 2


def test_failed_recompile_keeps_last_good_revision_and_project_spec(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Bookmarks API\nBuild a FastAPI app."})
    compiled = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Build a FastAPI app", tasks=[PlanTask(description="Build it")]),
        project_spec=ProjectSpec(
            name="Bookmarks API",
            slug="bookmarks-api",
            intent="new",
            workspace_root="projects/bookmarks-api",
            capabilities=["python", "fastapi", "pytest"],
            bootstrap_profile="fastapi",
            verifier=["uv", "run", "pytest", "-q"],
        ),
    )
    failed = PlanIntakeResult(
        status="failed",
        error="Plan compiler temporarily busy: another Workestra model operation is active.",
    )
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        side_effect=[compiled, failed],
    ):
        first = app.compile_plan(str(imported["id"]))
        retry = app.compile_plan(str(imported["id"]), {"force": True})

    saved = app.get_plan(str(imported["id"]))
    assert retry.error == failed.error
    assert saved["status"] == "compiled"
    assert saved["compiled_revision"] == first.compiled_revision == 1
    assert saved["plan"]["tasks"][0]["description"] == "Build it"
    assert saved["project_spec"]["slug"] == "bookmarks-api"
    assert saved["last_compile_attempt"]["status"] == "failed"
    assert saved["last_compile_attempt"]["error"] == failed.error
    assert [attempt["status"] for attempt in saved["compile_attempts"]] == ["compiled", "failed"]
    assert saved["compiled_revisions"] == [
        {
            "revision": 1,
            "compiled_at": saved["compiled_at"],
            "plan_digest": saved["compiled_digest"],
            "active": True,
            "reusable": True,
            "reason": None,
        }
    ]
    assert app.project_creation_eligibility(str(imported["id"]), 1)["eligible"] is True


def test_plan_history_groups_duplicate_source_and_prefers_latest_good_revision(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    markdown = "# Repeated source\nBuild a small Python tool."
    first = app.import_plan({"markdown": markdown})
    duplicate = app.import_plan({"markdown": markdown})
    first_result = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="First revision", tasks=[PlanTask(description="first")]),
    )
    second_result = PlanIntakeResult(
        status="compiled",
        plan=ExecutionPlan(request="Latest revision", tasks=[PlanTask(description="latest")]),
    )
    failure = PlanIntakeResult(status="failed", error="model temporarily busy")
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        side_effect=[first_result, second_result, failure],
    ):
        app.compile_plan(str(first["id"]))
        app.compile_plan(str(duplicate["id"]))
        app.compile_plan(str(duplicate["id"]), {"force": True})

    [source] = app.list_plan_history()
    assert source["source_digest"] == first["source_digest"]
    assert set(source["plan_ids"]) == {first["id"], duplicate["id"]}
    assert source["latest_good"] == {"plan_id": duplicate["id"], "revision": 1}
    assert [attempt["status"] for attempt in source["attempts"]] == ["compiled", "compiled", "failed"]
    assert source["latest_attempt"]["error"] == "model temporarily busy"


def test_use_plan_recovers_legacy_failed_record_from_matching_immutable_revision(tmp_path):
    app = ControlApplication(ProjectRegistry(tmp_path / "projects.json"))
    imported = app.import_plan({"markdown": "# Existing plan"})
    with patch(
        "local_agent_orchestrator.services.control_application.compile_markdown_plan",
        return_value=PlanIntakeResult(
            status="compiled",
            plan=ExecutionPlan(request="Keep this", tasks=[PlanTask(description="Preserve task")]),
        ),
    ):
        app.compile_plan(str(imported["id"]))

    legacy_failed = app._load_plan(str(imported["id"]))
    legacy_failed.update({
        "status": "failed",
        "error": "Plan compiler model unavailable: Another llama process is already running",
        "compiled_path": None,
        "compiled_revision": None,
        "compiled_digest": None,
        "compiled_at": None,
    })
    app._write_plan_record(legacy_failed)

    restored = app.get_plan(str(imported["id"]))
    assert restored["compiled"] is True
    assert restored["compiled_revision"] == 1
    assert restored["plan"]["tasks"][0]["description"] == "Preserve task"
    assert restored["last_compile_attempt"]["status"] == "failed"


def test_list_plans_filters_by_project_and_rejects_unknown_project(tmp_path):
    repo = tmp_path / "repo"
    second_repo = tmp_path / "repo-2"
    repo.mkdir()
    second_repo.mkdir()
    registry_path = tmp_path / "projects.json"
    app = ControlApplication(ProjectRegistry(registry_path))
    first = app.create_project("First", repo, ["pytest"])
    second = app.create_project("Second", second_repo, ["pytest"])
    imported = app.import_plan({"project_id": first.id, "markdown": "# First"})
    app.import_plan({"project_id": second.id, "markdown": "# Second"})

    assert [item["id"] for item in app.list_plans(first.id)] == [imported["id"]]
    with pytest.raises(KeyError, match="Project not found"):
        app.list_plans("missing")


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
