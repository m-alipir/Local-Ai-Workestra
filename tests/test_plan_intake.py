import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.adapters.llama_server import (
    LlamaServerBusyError,
    LlamaServerEmptyContentError,
)
from local_agent_orchestrator.models.config import (
    ModelConfig,
    OrchestratorSettings,
    ResourceSettings,
    Settings,
)
from local_agent_orchestrator.models.plan_intake import (
    PlanIntake,
    PlanIntakeResult,
)
from local_agent_orchestrator.services.plan_intake import (
    PLAN_CANDIDATE_RESPONSE_FORMAT,
    compile_plan,
    store_plan_markdown,
    validate_markdown,
)


def _settings() -> Settings:
    return Settings(
        orchestrator=OrchestratorSettings(
            model_start_timeout=3,
            model_stop_timeout=2,
        ),
        resources=ResourceSettings(
            minimum_free_ram_gb=1,
            minimum_free_vram_gb=1,
        ),
        paths={"runs": "runs"},
    )


def _bonsai() -> ModelConfig:
    return ModelConfig(
        role="deep_reasoning_architecture_design_retrospective",
        hf="local/bonsai",
        binary="/bin/llama-server",
        model_path="/models/bonsai.gguf",
        flash_attention=True,
        context=4096,
        reasoning="high",
    )


def _model_result() -> str:
    return json.dumps(
        {
            "request": "Add a small feature",
            "tasks": [
                {
                    "id": "implement",
                    "description": "Implement the feature",
                    "kind": "code",
                    "depends_on": [],
                    "verification": ["The focused test passes"],
                    "requires_approval": False,
                    "risk": "low",
                }
            ],
            "assumptions": ["The existing module is the integration point."],
            "unresolved_questions": [],
        }
    )


def test_validate_markdown_rejects_empty_untrusted_input():
    with pytest.raises(ValueError, match="Markdown cannot be empty"):
        validate_markdown("  \n")


def test_compiler_reports_active_model_process_as_temporary_busy():
    def busy_factory(**_kwargs):
        raise LlamaServerBusyError("another Workestra model process is active; retry shortly")

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
    ):
        result = compile_plan("# A small feature", server_factory=busy_factory)

    assert result.status == "failed"
    assert result.error.startswith("Plan compiler temporarily busy:")


def test_store_plan_markdown_writes_the_original_text(tmp_path):
    markdown = "# Rough plan\n\nAdd a feature.\n"

    intake = store_plan_markdown(markdown, tmp_path / "PLAN.md")

    assert isinstance(intake, PlanIntake)
    assert intake.markdown == markdown
    assert intake.stored_path == str(tmp_path / "PLAN.md")
    assert (tmp_path / "PLAN.md").read_text(encoding="utf-8") == markdown


def test_compile_plan_uses_bonsai_and_validates_candidate():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = _model_result()

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ) as server_type,
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert isinstance(result, PlanIntakeResult)
    assert result.status == "compiled"
    assert result.plan is not None
    assert result.plan.tasks[0].id == "implement"
    assert server.chat.call_args.kwargs["chat_template_kwargs"] == {
        "enable_thinking": False
    }
    assert server.chat.call_args.kwargs["require_content"] is True
    assert server.chat.call_args.kwargs["response_format"] == (
        PLAN_CANDIDATE_RESPONSE_FORMAT
    )
    server_type.assert_called_once_with(
        hf_model="local/bonsai",
        context=4096,
        binary="/bin/llama-server",
        model_path="/models/bonsai.gguf",
        flash_attention=True,
        minimum_free_ram_gb=1,
        minimum_free_vram_gb=1,
        start_timeout=3,
        stop_timeout=2,
        reasoning="high",
    )


def test_compile_plan_rejects_test_execution_without_code_prerequisite():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build and test a feature",
            "tasks": [
                {
                    "id": "verify",
                    "description": "Run the trusted test suite",
                    "kind": "test",
                    "depends_on": [],
                },
                {
                    "id": "implement",
                    "description": "Implement the feature and create test files",
                    "kind": "code",
                    "depends_on": [],
                },
            ],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Build and test\nImplement the feature.")

    assert result.status == "failed"
    assert "must depend on at least one code task" in (result.error or "")


def test_compile_plan_accepts_verifier_with_transitive_code_prerequisite(tmp_path):
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build a local bookmarks API",
            "project": {
                "name": "Local Bookmarks API",
                "intent": "new",
                "language": "Python",
                "framework": "FastAPI",
                "database": "SQLite",
                "project_type": "API",
            },
            "tasks": [
                {
                    "id": "task-001",
                    "description": "Implement the bookmarks API and its tests.",
                    "kind": "code",
                },
                {
                    "id": "task-002",
                    "description": "Write the local run instructions.",
                    "kind": "docs",
                    "depends_on": ["task-001"],
                },
                {
                    "id": "task-003",
                    "description": "Run the trusted test suite.",
                    "kind": "test",
                    "depends_on": ["task-002"],
                },
            ],
        }
    )

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
        patch("local_agent_orchestrator.services.plan_intake.LlamaServer", return_value=server),
    ):
        result = compile_plan(
            "# Local Bookmarks API\nBuild a FastAPI SQLite API.",
            projects_root=tmp_path / "Projeler",
        )

    assert result.status == "compiled"
    assert result.plan is not None
    assert result.plan.tasks[-1].id == "task-003"
    assert result.project_spec is not None
    assert result.project_spec.workspace_root == str(tmp_path / "Projeler" / "local-bookmarks-api")


def test_local_bookmarks_compiler_derives_full_suite_verifier_dependencies():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build a local bookmarks API",
            "project": {
                "name": "Local Bookmarks API",
                "intent": "new",
                "language": "Python",
                "framework": "FastAPI",
                "database": "SQLite",
                "project_type": "API",
            },
            "tasks": [
                {
                    "id": "task-001",
                    "description": "Implement the FastAPI bookmarks service.",
                    "kind": "code",
                    "primary_scope": ["app/"],
                },
                {
                    "id": "task-002",
                    "description": "Create the endpoint and persistence tests.",
                    "kind": "code",
                    "primary_scope": ["tests/"],
                    "depends_on": ["task-001"],
                },
                {
                    "id": "task-003",
                    "description": "Write the README with local run instructions.",
                    "kind": "docs",
                    "depends_on": ["task-002"],
                },
                {
                    "id": "task-004",
                    "description": "Run the trusted test suite.",
                    "kind": "test",
                },
            ],
        }
    )

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
        patch("local_agent_orchestrator.services.plan_intake.LlamaServer", return_value=server),
    ):
        result = compile_plan(
            "# Local Bookmarks API\nBuild a FastAPI SQLite bookmarks service."
        )

    assert result.status == "compiled"
    assert result.plan is not None
    assert result.plan.tasks[-1].depends_on == ["task-001", "task-002"]
    assert result.project_spec is not None


def test_compile_plan_rejects_test_creation_misclassified_as_execution():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Add tests",
            "tasks": [
                {
                    "id": "tests",
                    "description": "Add automated tests for the endpoint",
                    "kind": "test",
                }
            ],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Add tests\nAdd endpoint tests.")

    assert result.status == "failed"
    assert "describes creating tests" in (result.error or "")


def test_compile_plan_returns_controlled_failure_when_model_unavailable():
    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            side_effect=RuntimeError("model config unavailable"),
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert result.plan is None
    assert "model config unavailable" in result.error


def test_compile_plan_rejects_deploy_and_shell_intent_before_model_call():
    server = MagicMock()

    with patch(
        "local_agent_orchestrator.services.plan_intake.LlamaServer",
        return_value=server,
    ) as server_type:
        result = compile_plan(
            "# Plan\nDeploy to production with an arbitrary shell command."
        )

    assert result.status == "rejected"
    assert result.plan is None
    assert result.unresolved_issues
    server_type.assert_not_called()


def test_compile_plan_rejects_non_strict_model_output():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Feature",
            "tasks": [
                {
                    "description": "Implement it",
                    "unexpected": "must be rejected",
                }
            ],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert result.plan is None
    assert "strict Plan v2 candidate" in result.error


def test_compile_plan_retries_one_empty_model_response_without_repairing_json():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.side_effect = ["", _model_result()]

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "compiled"
    assert server.chat.call_count == 2


def test_compile_plan_returns_controlled_failure_for_empty_compiler_output():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = ""

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert result.plan is None
    assert "empty assistant content after one retry" in result.error


def test_compile_plan_bounds_empty_response_retry_to_one_retry():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.side_effect = ["", "", "unexpected third call"]

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert server.chat.call_count == 2


def test_compile_plan_preserves_empty_response_diagnostics_after_retry():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.side_effect = [
        LlamaServerEmptyContentError(
            "llama-server returned empty assistant content "
            "(finish_reason='length'; message_fields=content,reasoning_content; "
            "reasoning_content_present=True)"
        ),
        LlamaServerEmptyContentError(
            "llama-server returned empty assistant content "
            "(finish_reason='length'; message_fields=content,reasoning_content; "
            "reasoning_content_present=True)"
        ),
    ]

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert "finish_reason='length'" in result.error
    assert "reasoning_content_present=True" in result.error
    assert server.chat.call_count == 2


def test_compile_plan_returns_controlled_failure_for_malformed_json():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = "{not valid json"

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert result.plan is None
    assert "Invalid strict Plan v2 candidate" in result.error


def test_compile_plan_surfaces_controlled_model_diagnostics():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.side_effect = RuntimeError("compiler timed out")

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert result.error == "Plan compiler model unavailable: compiler timed out"


def test_compile_plan_rejects_invalid_dependency_graph():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Feature",
            "tasks": [
                {
                    "id": "a",
                    "description": "First",
                    "depends_on": ["missing"],
                }
            ],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "failed"
    assert "unknown task" in result.error
    assert "known IDs: a" in result.error


def test_compile_plan_keeps_verification_as_metadata():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Feature",
            "tasks": [
                {
                    "id": "a",
                    "description": "Implement it",
                    "verification": ["$(touch /tmp/should-not-run)"],
                }
            ],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a feature.")

    assert result.status == "compiled"
    assert result.plan.tasks[0].verification == [
        "$(touch /tmp/should-not-run)"
    ]


def test_compiler_commentary_does_not_trigger_unsafe_policy_false_positive():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Add a helper",
            "tasks": [{"description": "Implement the helper", "kind": "code"}],
            "assumptions": ["Deployment remains outside this local task."],
            "unresolved_questions": [],
        }
    )

    with (
        patch(
            "local_agent_orchestrator.services.plan_intake.load_settings",
            return_value=_settings(),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.load_models",
            return_value=MagicMock(models={"bonsai2": _bonsai()}),
        ),
        patch(
            "local_agent_orchestrator.services.plan_intake.LlamaServer",
            return_value=server,
        ),
    ):
        result = compile_plan("# Rough plan\nAdd a helper.")

    assert result.status == "compiled"


def test_compiler_emits_fastapi_project_spec_for_greenfield_plan():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build a bookmarks API",
            "project": {
                "name": "Bookmarks API",
                "intent": "new",
                "language": "Python",
                "framework": "FastAPI",
                "database": "SQLite",
                "project_type": "API",
            },
            "tasks": [{"description": "Implement the API", "kind": "code"}],
        }
    )

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
        patch("local_agent_orchestrator.services.plan_intake.LlamaServer", return_value=server),
    ):
        result = compile_plan("# Bookmarks API\nBuild a FastAPI SQLite API.")

    assert result.status == "compiled"
    assert result.project_spec is not None
    assert result.project_spec.bootstrap_profile == "fastapi"
    assert result.project_spec.workspace_root == str(Path.home() / "Projeler" / "bookmarks-api")


def test_compiler_treats_crud_persistence_and_search_as_app_features_not_capabilities():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build a local bookmarks API",
            "project": {
                "name": "Local Bookmarks API",
                "intent": "new",
                "language": "Python",
                "framework": "FastAPI",
                "database": "SQLite",
                "capabilities": [
                    "CRUD",
                    "Persistence",
                    "Search",
                    "Python",
                    "FastAPI",
                    "SQLite",
                    "FastAPI TestClient",
                ],
            },
            "tasks": [{"description": "Implement bookmarks CRUD, persistence, and search", "kind": "code"}],
        }
    )

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
        patch("local_agent_orchestrator.services.plan_intake.LlamaServer", return_value=server),
    ):
        result = compile_plan("# Local Bookmarks API\nImplement CRUD, SQLite persistence, and search.")

    assert result.status == "compiled"
    assert result.project_spec is not None
    assert result.project_spec.bootstrap_profile == "fastapi"
    assert {"python", "fastapi", "sqlite", "pytest", "api-testing", "sqlalchemy"} <= set(result.project_spec.capabilities)
    assert not result.project_spec.research_requirements
    assert not result.unresolved_issues
    assert "application features such as CRUD, search, or" in server.chat.call_args.kwargs["prompt"]
    assert "persistence in `capabilities`" in server.chat.call_args.kwargs["prompt"]


def test_compiler_returns_project_spec_and_research_for_untrusted_frontend_stack():
    server = MagicMock()
    server.__enter__.return_value = server
    server.chat.return_value = json.dumps(
        {
            "request": "Build a frontend",
            "project": {
                "name": "Bookmarks Web",
                "intent": "new",
                "language": "TypeScript",
                "framework": "React",
                "project_type": "frontend",
            },
            "tasks": [{"description": "Implement the frontend", "kind": "code"}],
        }
    )

    with (
        patch("local_agent_orchestrator.services.plan_intake.load_settings", return_value=_settings()),
        patch("local_agent_orchestrator.services.plan_intake.load_models", return_value=MagicMock(models={"bonsai2": _bonsai()})),
        patch("local_agent_orchestrator.services.plan_intake.LlamaServer", return_value=server),
    ):
        result = compile_plan("# Bookmarks Web\nBuild a React TypeScript frontend.")

    assert result.status == "rejected"
    assert result.plan is not None
    assert result.project_spec is not None
    assert result.project_spec.research_requirements
    assert any("Node/TypeScript" in issue for issue in result.unresolved_issues)
