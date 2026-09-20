import json
from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.services.sol_planner import (
    SolPlannerError,
    build_plan_with_codex,
)


def test_build_plan_with_codex(tmp_path):
    def fake_run(command, capture_output, text):
        output_index = command.index(
            "--output-last-message"
        ) + 1

        output_path = command[output_index]

        with open(output_path, "w") as file:
            json.dump(
                {
                    "request": "Build calculator",
                    "tasks": [
                        {
                            "description": "Create calculator module"
                        },
                        {
                            "description": "Add tests"
                        },
                    ],
                },
                file,
            )

        return MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )

    with patch(
        "local_agent_orchestrator.services.sol_planner.subprocess.run",
        side_effect=fake_run,
    ):
        plan = build_plan_with_codex(
            request="Build calculator",
            workspace_root=tmp_path,
        )

    assert plan.request == "Build calculator"
    assert len(plan.tasks) == 2


def test_planner_plan_v2_fields_use_runtime_validation(tmp_path):
    def fake_run(command, capture_output, text):
        schema = json.loads(
            open(command[command.index("--output-schema") + 1]).read()
        )
        properties = schema["properties"]["tasks"]["items"]["properties"]
        assert {
            "id",
            "description",
            "kind",
            "depends_on",
            "verification",
            "requires_approval",
            "risk",
        } <= set(properties)
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w") as file:
            json.dump(
                {
                    "request": "Build calculator",
                    "tasks": [
                        {
                            "id": "tests",
                            "description": "Run tests",
                            "kind": "test",
                            "depends_on": ["code"],
                            "verification": ["pytest result is zero"],
                            "requires_approval": False,
                            "risk": "low",
                        },
                        {
                            "id": "code",
                            "description": "Implement calculator",
                            "kind": "code",
                            "risk": "low",
                        },
                    ],
                },
                file,
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch(
        "local_agent_orchestrator.services.sol_planner.subprocess.run",
        side_effect=fake_run,
    ):
        plan = build_plan_with_codex(
            request="Build calculator",
            workspace_root=tmp_path,
        )

    assert plan.tasks[0].kind == "test"
    assert plan.tasks[0].depends_on == ["code"]


def test_planner_rejects_dependency_cycle(tmp_path):
    def fake_run(command, capture_output, text):
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w") as file:
            json.dump(
                {
                    "request": "cycle",
                    "tasks": [
                        {"id": "a", "description": "A", "depends_on": ["b"]},
                        {"id": "b", "description": "B", "depends_on": ["a"]},
                    ],
                },
                file,
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch(
            "local_agent_orchestrator.services.sol_planner.subprocess.run",
            side_effect=fake_run,
        ),
        pytest.raises(SolPlannerError, match="dependency graph"),
    ):
        build_plan_with_codex(
            request="cycle",
            workspace_root=tmp_path,
        )
