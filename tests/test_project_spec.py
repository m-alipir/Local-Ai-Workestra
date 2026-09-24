import pytest

from local_agent_orchestrator.models.plan_intake import (
    PlanCandidate,
    PlanCandidateProject,
    PlanCandidateTask,
)
from local_agent_orchestrator.models.plan import PlanTask
from local_agent_orchestrator.models.project_spec import ProjectSpec
from local_agent_orchestrator.services.project_spec import derive_project_spec
from pathlib import Path


def _candidate(project: PlanCandidateProject, request: str) -> PlanCandidate:
    return PlanCandidate(
        request=request,
        project=project,
        tasks=[PlanCandidateTask(description="Implement and verify the project")],
    )


def test_fastapi_project_derives_trusted_greenfield_spec(tmp_path):
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Local Bookmarks API",
                language="Python",
                framework="FastAPI",
                project_type="API",
                database="SQLite",
                capabilities=["python", "fastapi", "sqlite", "pytest", "api-testing", "create_bookmark", "list_bookmarks", "lookup_bookmark", "url_validation"],
                completion_criteria=["The API tests pass"],
            ),
            "Build a FastAPI bookmarks API",
        ),
        "# Local Bookmarks API\nBuild a FastAPI bookmarks API with SQLite.",
        projects_root=tmp_path / "Projeler",
    )

    assert spec.intent == "new"
    assert spec.slug == "local-bookmarks-api"
    assert spec.workspace_root == str(tmp_path / "Projeler" / "local-bookmarks-api")
    assert {"python", "fastapi", "sqlite", "sqlalchemy", "pytest", "api-testing"} <= set(spec.capabilities)
    assert spec.language == "Python"
    assert spec.framework == "FastAPI"
    assert spec.database == "SQLite"
    assert spec.bootstrap_profile == "fastapi"
    assert spec.verifier == ["uv", "run", "pytest", "-q"]
    assert spec.research_requirements == []


def test_greenfield_workspace_uses_configured_projects_root(tmp_path):
    projects_root = tmp_path / "Projeler"
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Local Bookmarks API",
                intent="new",
                language="Python",
                framework="FastAPI",
                capabilities=["python", "fastapi"],
            ),
            "Build a bookmarks API",
        ),
        "# Local Bookmarks API\nBuild a bookmarks API.",
        projects_root=projects_root,
    )

    assert Path(spec.workspace_root) == projects_root / "local-bookmarks-api"
    assert not Path(spec.workspace_root).is_relative_to(tmp_path / ".config")


def test_greenfield_workspace_uses_deterministic_suffix_around_existing_work(tmp_path):
    projects_root = tmp_path / "Projeler"
    (projects_root / "local-bookmarks-api").mkdir(parents=True)
    (projects_root / "local-bookmarks-api" / ".git").mkdir()
    (projects_root / "local-bookmarks-api-2").mkdir()
    (projects_root / "local-bookmarks-api-2" / "README.md").write_text("keep", encoding="utf-8")

    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(name="Local Bookmarks API", language="Python", framework="FastAPI"),
            "Build a bookmarks API",
        ),
        "# Local Bookmarks API\nBuild a bookmarks API.",
        projects_root=projects_root,
    )

    assert spec.slug == "local-bookmarks-api-3"
    assert spec.workspace_root == str(projects_root / "local-bookmarks-api-3")


def test_greenfield_workspace_skips_registered_path_and_project_id(tmp_path):
    projects_root = tmp_path / "Projeler"
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(name="Local Bookmarks API", language="Python", framework="FastAPI"),
            "Build a bookmarks API",
        ),
        "# Local Bookmarks API\nBuild a bookmarks API.",
        projects_root=projects_root,
        occupied_workspace_paths=[projects_root / "local-bookmarks-api"],
        occupied_project_ids=["local-bookmarks-api"],
    )

    assert spec.slug == "local-bookmarks-api-2"
    assert spec.workspace_root == str(projects_root / "local-bookmarks-api-2")


def test_node_frontend_project_is_explicitly_blocked_for_research():
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Bookmarks Web",
                language="TypeScript",
                framework="React",
                project_type="frontend",
                runtime="Node",
            ),
            "Build a React TypeScript frontend",
        ),
        "# Bookmarks Web\nBuild a React TypeScript frontend with Vite.",
    )

    assert {"node", "typescript", "react", "vite"} <= set(spec.capabilities)
    assert spec.bootstrap_profile is None
    assert spec.verifier is None
    assert any("Node/TypeScript" in item.topic for item in spec.research_requirements)


def test_godot_project_does_not_invent_engine_or_verifier_setup():
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Tiny Godot Game",
                engine="Godot",
                project_type="game",
                runtime="GDScript",
            ),
            "Build a small Godot game",
        ),
        "# Tiny Godot Game\nBuild a small Godot game in GDScript.",
    )

    assert {"godot", "gdscript"} <= set(spec.capabilities)
    assert spec.bootstrap_profile is None
    assert spec.verifier is None
    assert len(spec.research_requirements) == 2


def test_unknown_capability_becomes_research_not_setup_authority():
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Specialized Tool",
                capabilities=["unregistered-runtime"],
            ),
            "Build a specialized tool",
        ),
        "# Specialized Tool\nBuild a specialized tool.",
    )

    assert "unregistered-runtime" not in spec.capabilities
    assert spec.bootstrap_profile is None
    assert any(item.topic == "capability:unregistered-runtime" for item in spec.research_requirements)


def test_generated_capability_labels_are_canonicalized_but_unknowns_stay_blocking():
    spec = derive_project_spec(
        _candidate(
            PlanCandidateProject(
                name="Local Bookmarks API",
                intent="new",
                capabilities=[
                    "CRUD",
                    "crud",
                    "Persistence",
                    "Search",
                    "Python",
                    "FastAPI",
                    "SQLite",
                    "FastAPI TestClient",
                    "unregistered-runtime",
                ],
            ),
            "Build a FastAPI SQLite bookmarks API",
        ),
        "# Local Bookmarks API\nBuild a FastAPI SQLite bookmarks API.",
    )

    assert {"python", "fastapi", "sqlite", "pytest", "api-testing", "sqlalchemy"} <= set(spec.capabilities)
    assert not {"crud", "persistence", "search"} & set(spec.capabilities)
    assert [item.topic for item in spec.research_requirements] == ["capability:unregistered-runtime"]


def test_project_spec_and_task_boundaries_reject_untrusted_execution_inputs():
    with pytest.raises(ValueError, match="trusted verifier"):
        ProjectSpec(
            name="Unsafe",
            slug="unsafe",
            verifier=["sh", "-c", "pytest"],
        )
    with pytest.raises(ValueError, match="safe relative paths"):
        PlanTask(description="Unsafe", file_boundaries=["../outside"])
    assert PlanTask(description="Directory", file_boundaries=["tests/"]).file_boundaries == ["tests/"]
