import subprocess
from unittest.mock import MagicMock, patch

from local_agent_orchestrator.services.coding_context import CodingContext
from local_agent_orchestrator.services.coding_executor import (
    execute_coding_task,
)


def test_execute_coding_task(tmp_path):
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
    (tmp_path / ".keep").write_text("\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=tmp_path,
        check=True,
    )

    fake_agent = MagicMock()

    fake_agent.run.return_value.content = (
        __import__("json").dumps({
            "operations": [{
                "kind": "create_file",
                "path": "hello.py",
                "content": "print(\"hello\")\n",
            }]
        })
    )

    context = CodingContext(
        task="Create hello.py",
        exploration_summary="No existing implementation found.",
        exploration_transcript="",
    )

    with (
        patch(
            "local_agent_orchestrator.services.coding_executor.QwenCoderAgent",
            return_value=fake_agent,
        ),
        patch(
            "local_agent_orchestrator.services.coding_executor.build_coding_context",
            return_value=context,
        ),
    ):
        changed = execute_coding_task(
            "Create hello.py",
            tmp_path,
        )

    assert changed == ["hello.py"]
    assert (tmp_path / "hello.py").read_text() == "print(\"hello\")\n"


def test_coder_prompt_spells_out_kind_specific_operation_fields(tmp_path):
    context = CodingContext(
        task="Update app.py",
        exploration_summary="app.py contains value = 1.",
        exploration_transcript="app.py evidence",
        grounded_paths=("app.py",),
    )
    fake_agent = MagicMock()
    fake_agent.run.return_value.content = __import__("json").dumps({
        "operations": [{
            "kind": "replace_exact",
            "path": "app.py",
            "old_text": "value = 1",
            "new_text": "value = 2",
        }]
    })

    with (
        patch(
            "local_agent_orchestrator.services.coding_executor.QwenCoderAgent",
            return_value=fake_agent,
        ),
        patch(
            "local_agent_orchestrator.services.coding_executor.build_coding_context",
            return_value=context,
        ),
        patch(
            "local_agent_orchestrator.services.coding_executor.apply_edit_operations",
            return_value=["app.py"],
        ),
    ):
        execute_coding_task("Update app.py", tmp_path)

    prompt = fake_agent.run.call_args.args[0]
    assert "replace_exact requires non-empty old_text and new_text" in prompt
    assert "create_file requires complete content" in prompt
    assert "create_file content must not contain trailing spaces or tabs" in prompt
    assert "delete_file requires only kind and path" in prompt
