from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.agents.repo_explorer import RESPONSE_FORMAT
from local_agent_orchestrator.services.repo_explorer import (
    RepoExplorationError,
    _parse_response,
    explore_repository,
)


def test_explorer_response_schema_keeps_optional_action_fields_optional():
    schema = RESPONSE_FORMAT["json_schema"]["schema"]

    assert schema["required"] == ["type"]
    assert schema["properties"]["tool"]["type"] == "string"
    assert schema["additionalProperties"] is False


def test_parse_tool_response():
    value = _parse_response(
        '{"type":"tool","tool":"search_text","query":"greet"}'
    )

    assert value["type"] == "tool"
    assert value["tool"] == "search_text"


def test_parse_response_allows_trailing_text():
    value = _parse_response(
        '{"type":"final","summary":"done"}\nextra'
    )

    assert value["summary"] == "done"


def test_explorer_uses_tool_then_finishes(tmp_path):
    (tmp_path / "app.py").write_text(
        "def greet(name):\n"
        "    return f'Hello {name}'\n"
    )

    fake_agent = MagicMock()
    fake_agent.run_step.side_effect = [
        (
            '{"type":"tool",'
            '"tool":"search_text",'
            '"query":"greet",'
            '"path":null,'
            '"max_results":20}'
        ),
        (
            '{"type":"tool",'
            '"tool":"read_file",'
            '"path":"app.py"}'
        ),
        (
            '{"type":"final",'
            '"summary":"app.py contains greet(name)."}'
        ),
    ]

    with patch(
        "local_agent_orchestrator.services.repo_explorer.QwenRepoExplorer",
        return_value=fake_agent,
    ):
        result = explore_repository(
            task="Add farewell",
            workspace_root=str(tmp_path),
            max_steps=5,
        )

    assert result.summary == "app.py contains greet(name)."
    assert result.steps == 3
    assert "app.py" in result.observed_paths
    assert fake_agent.run_step.call_count == 3

    final_call = fake_agent.run_step.call_args_list[-1]

    assert "app.py:1" in final_call.kwargs[
        "transcript"
    ]
    assert "def greet" in final_call.kwargs[
        "transcript"
    ]


def test_explorer_stops_at_step_limit(tmp_path):
    fake_agent = MagicMock()
    fake_agent.run_step.return_value = (
        '{"type":"tool",'
        '"tool":"list_files",'
        '"path":null}'
    )

    with patch(
        "local_agent_orchestrator.services.repo_explorer.QwenRepoExplorer",
        return_value=fake_agent,
    ):
        with pytest.raises(
            RepoExplorationError,
            match="final summary",
        ):
            explore_repository(
                task="Inspect repo",
                workspace_root=str(tmp_path),
                max_steps=2,
            )


def test_explorer_accepts_direct_tool_type(tmp_path):
    fake_agent = MagicMock()
    fake_agent.run_step.side_effect = [
        '{"type":"read_file","path":"README.md"}',
        '{"type":"final","summary":"Read the README."}',
    ]

    (tmp_path / "README.md").write_text("hello\n")

    with patch(
        "local_agent_orchestrator.services.repo_explorer.QwenRepoExplorer",
        return_value=fake_agent,
    ):
        result = explore_repository(
            task="Inspect repo",
            workspace_root=str(tmp_path),
            max_steps=2,
        )

    assert result.summary == "Read the README."



def test_explorer_accepts_missing_type_when_tool_is_present(tmp_path):
    fake_agent = MagicMock()
    fake_agent.run_step.side_effect = [
        '{"tool":"read_file","path":"README.md"}',
        '{"type":"final","summary":"Read the README."}',
    ]

    (tmp_path / "README.md").write_text("hello\n")

    with patch(
        "local_agent_orchestrator.services.repo_explorer.QwenRepoExplorer",
        return_value=fake_agent,
    ):
        result = explore_repository(
            task="Inspect repo",
            workspace_root=str(tmp_path),
            max_steps=2,
        )

    assert result.summary == "Read the README."
