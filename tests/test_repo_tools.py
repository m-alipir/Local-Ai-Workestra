import subprocess

from local_agent_orchestrator.models.tool_action import ToolAction
from local_agent_orchestrator.services.repo_tools import RepoTools


def init_repo(path):
    subprocess.run(
        ["git", "init", "-q"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
    )


def test_list_and_read_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def hello():\n    return 'hello'\n"
    )

    tools = RepoTools(tmp_path)

    listing = tools.execute(
        ToolAction(
            tool="list_files",
            path="src",
        )
    )

    assert listing.ok is True
    assert "src/app.py" in listing.content

    result = tools.execute(
        ToolAction(
            tool="read_file",
            path="src/app.py",
        )
    )

    assert result.ok is True
    assert "def hello" in result.content


def test_search_text(tmp_path):
    (tmp_path / "app.py").write_text(
        "def greet(name):\n"
        "    return f'Hello {name}'\n"
    )

    tools = RepoTools(tmp_path)

    result = tools.execute(
        ToolAction(
            tool="search_text",
            query="greet",
        )
    )

    assert result.ok is True
    assert "app.py:1" in result.content


def test_path_escape_is_blocked(tmp_path):
    tools = RepoTools(tmp_path)

    result = tools.execute(
        ToolAction(
            tool="read_file",
            path="../secret.txt",
        )
    )

    assert result.ok is False
    assert "escapes workspace" in result.content


def test_git_status_and_diff(tmp_path):
    init_repo(tmp_path)

    file = tmp_path / "app.py"
    file.write_text("value = 1\n")

    subprocess.run(
        ["git", "add", "app.py"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=tmp_path,
        check=True,
    )

    file.write_text("value = 2\n")

    tools = RepoTools(tmp_path)

    status = tools.execute(
        ToolAction(tool="git_status")
    )

    diff = tools.execute(
        ToolAction(tool="git_diff")
    )

    assert status.ok is True
    assert "app.py" in status.content

    assert diff.ok is True
    assert "-value = 1" in diff.content
    assert "+value = 2" in diff.content
