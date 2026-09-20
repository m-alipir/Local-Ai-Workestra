import json
import subprocess
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.services.coding_context import CodingContext
from local_agent_orchestrator.services.coding_executor import (
    execute_coding_task,
)


def test_coding_executor_uses_repository_context(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "app.py").write_text(
        "def greet(name):\n"
        "    return f\"Hello {name}\"\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=tmp_path,
        check=True,
    )

    context = CodingContext(
        task="Add farewell",
        exploration_summary="app.py contains greet(name).",
        exploration_transcript=(
            "ACTION:\n"
            "{\"tool\":\"read_file\",\"path\":\"app.py\"}\n"
            "OBSERVATION:\n"
            "def greet(name):\n"
            "    return f\"Hello {name}\"\n"
        ),
        grounded_paths=("app.py",),
    )

    fake_agent = MagicMock()
    fake_agent.run.return_value = MagicMock(
        content=json.dumps({
            "operations": [{
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": '    return f"Hello {name}"',
                "new_text": (
                    '    return f"Hello {name}"\n\n'
                    'def farewell(name):\n'
                    '    return f"Goodbye {name}"'
                ),
            }]
        })
    )

    with (
        patch(
            "local_agent_orchestrator.services.coding_executor.build_coding_context",
            return_value=context,
        ) as context_builder,
        patch(
            "local_agent_orchestrator.services.coding_executor.QwenCoderAgent",
            return_value=fake_agent,
        ),
    ):
        changed = execute_coding_task(
            task="Add farewell",
            workspace_root=tmp_path,
        )

    assert changed == ["app.py"]

    output = (tmp_path / "app.py").read_text()

    assert "def greet" in output
    assert "def farewell" in output

    prompt = fake_agent.run.call_args.args[0]

    assert "app.py contains greet(name)" in prompt
    assert "def greet(name)" in prompt

    context_builder.assert_called_once_with(
        task="Add farewell",
        workspace_root=str(tmp_path),
    )
