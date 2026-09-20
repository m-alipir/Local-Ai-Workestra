import pytest

from local_agent_orchestrator.services.workspace import (
    Workspace,
    WorkspaceError,
)


def test_read_and_write(tmp_path):
    workspace = Workspace(tmp_path)

    workspace.write_text("src/test.py", "print(123)\n")

    assert workspace.exists("src/test.py")
    assert workspace.read_text("src/test.py") == "print(123)\n"


def test_blocks_parent_escape(tmp_path):
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspaceError):
        workspace.read_text("../secret.txt")


def test_blocks_absolute_escape(tmp_path):
    workspace = Workspace(tmp_path)

    with pytest.raises(WorkspaceError):
        workspace.write_text("/tmp/evil.txt", "bad")
