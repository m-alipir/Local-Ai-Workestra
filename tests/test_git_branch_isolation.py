import subprocess

import pytest

from local_agent_orchestrator.services.git_workspace import (
    GitWorkspace,
    GitWorkspaceError,
)


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

    (path / "README.md").write_text("test\n")

    subprocess.run(
        ["git", "add", "-A"],
        cwd=path,
        check=True,
    )

    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=path,
        check=True,
    )


def test_create_agent_branch(tmp_path):
    init_repo(tmp_path)

    git = GitWorkspace(tmp_path)
    git.assert_clean()

    branch = git.create_agent_branch(
        "run123"
    )

    assert branch == "agent/run123"
    assert git.current_branch() == "agent/run123"


def test_existing_agent_branch_is_reused(tmp_path):
    init_repo(tmp_path)

    git = GitWorkspace(tmp_path)
    git.assert_clean()

    first = git.create_agent_branch(
        "run123"
    )

    second = git.create_agent_branch(
        "another-run"
    )

    assert first == "agent/run123"
    assert second == "agent/run123"


def test_branch_creation_requires_clean_baseline(tmp_path):
    init_repo(tmp_path)

    git = GitWorkspace(tmp_path)

    with pytest.raises(
        GitWorkspaceError,
        match="Clean baseline",
    ):
        git.create_agent_branch(
            "run123"
        )


def test_existing_target_agent_branch_is_rejected(tmp_path):
    init_repo(tmp_path)

    subprocess.run(
        ["git", "branch", "agent/run123"],
        cwd=tmp_path,
        check=True,
    )

    git = GitWorkspace(tmp_path)
    git.assert_clean()

    with pytest.raises(
        GitWorkspaceError,
        match="already exists",
    ):
        git.create_agent_branch(
            "run123"
        )


def test_run_id_is_sanitized_for_branch_name(tmp_path):
    init_repo(tmp_path)

    git = GitWorkspace(tmp_path)
    git.assert_clean()

    branch = git.create_agent_branch(
        "run id/with spaces"
    )

    assert branch == "agent/run-id-with-spaces"
