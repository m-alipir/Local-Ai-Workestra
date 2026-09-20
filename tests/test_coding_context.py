from unittest.mock import patch

from local_agent_orchestrator.services.coding_context import (
    CodingContext,
    build_coding_context,
)
from local_agent_orchestrator.services.repo_explorer import (
    ExplorationResult,
)


def test_coding_context_prompt_contains_repo_evidence():
    context = CodingContext(
        task="Add farewell",
        exploration_summary="app.py defines greet(name).",
        exploration_transcript=(
            "ACTION:\nread_file app.py\n"
            "OBSERVATION:\ndef greet(name): ..."
        ),
    )

    prompt = context.as_prompt()

    assert "Add farewell" in prompt
    assert "app.py defines greet(name)" in prompt
    assert "def greet(name)" in prompt
    assert "exact contiguous excerpt" in prompt
    assert "complete content" in prompt


def test_build_coding_context_uses_explorer(tmp_path):
    exploration = ExplorationResult(
        summary="Relevant code is in app.py.",
        steps=2,
        transcript="OBSERVATION:\napp.py contents",
        observed_paths=("app.py",),
    )

    with patch(
        "local_agent_orchestrator.services.coding_context.explore_repository",
        return_value=exploration,
    ) as explorer:
        context = build_coding_context(
            task="Add farewell",
            workspace_root=str(tmp_path),
        )

    assert context.task == "Add farewell"
    assert context.exploration_summary == "Relevant code is in app.py."
    assert "app.py contents" in context.exploration_transcript
    assert context.grounded_paths == ("app.py",)

    explorer.assert_called_once_with(
        task="Add farewell",
        workspace_root=str(tmp_path),
        max_steps=16,
    )
