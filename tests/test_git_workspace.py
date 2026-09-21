import subprocess
from unittest.mock import patch

import pytest

from local_agent_orchestrator.services.git_workspace import (
    GitWorkspace,
    GitWorkspaceError,
)


def git(root, *args):
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )


def make_repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test User")

    (tmp_path / "app.py").write_text("x = 1\n")

    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "initial")

    return GitWorkspace(tmp_path)


def test_clean_repository(tmp_path):
    workspace = make_repo(tmp_path)

    workspace.assert_clean()

    assert workspace.status() == []


def test_dirty_repository_is_blocked(tmp_path):
    workspace = make_repo(tmp_path)

    (tmp_path / "app.py").write_text("x = 2\n")

    with pytest.raises(GitWorkspaceError):
        workspace.assert_clean()


def test_checkpoint_commits_changes(tmp_path):
    workspace = make_repo(tmp_path)
    workspace.assert_clean()

    old_head = workspace.head()

    (tmp_path / "app.py").write_text("x = 2\n")

    new_head = workspace.checkpoint(
        "agent: implement task"
    )

    assert new_head != old_head
    assert workspace.status() == []


def test_checkpoint_uses_fallback_identity_without_git_config(tmp_path):
    git(tmp_path, "init")
    (tmp_path / "app.py").write_text("x = 1\n")
    git(
        tmp_path,
        "-c",
        "user.name=Bootstrap",
        "-c",
        "user.email=bootstrap@example.com",
        "add",
        "-A",
    )
    git(
        tmp_path,
        "-c",
        "user.name=Bootstrap",
        "-c",
        "user.email=bootstrap@example.com",
        "commit",
        "-m",
        "initial",
    )

    workspace = GitWorkspace(tmp_path)
    workspace.assert_clean()
    (tmp_path / "app.py").write_text("x = 2\n")

    workspace.checkpoint("agent: update app")

    identity = git(
        tmp_path,
        "show",
        "-s",
        "--format=%an <%ae>",
    ).stdout.strip()
    assert identity == "local-agent-orchestrator <local-agent-orchestrator@localhost>"

    for key in ("user.name", "user.email"):
        configured = subprocess.run(
            ["git", "config", "--local", "--get", key],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert configured.returncode != 0


def test_checkpoint_does_not_hide_git_config_lookup_failure(tmp_path):
    workspace = make_repo(tmp_path)
    workspace.assert_clean()
    (tmp_path / "app.py").write_text("x = 2\n")

    real_run = workspace._run

    def fake_run(*args, **kwargs):
        if args[:3] == ("config", "--local", "--get"):
            return subprocess.CompletedProcess(
                args=["git", *args],
                returncode=2,
                stdout="",
                stderr="git config lookup failed",
            )
        return real_run(*args, **kwargs)

    with patch.object(workspace, "_run", side_effect=fake_run):
        with pytest.raises(
            GitWorkspaceError,
            match="git config lookup failed",
        ):
            workspace.checkpoint("agent: update app")

    workspace.rollback()
    assert workspace.status() == []


def test_rollback_restores_clean_baseline(tmp_path):
    workspace = make_repo(tmp_path)
    workspace.assert_clean()

    (tmp_path / "app.py").write_text("broken\n")
    (tmp_path / "new_file.py").write_text("temporary\n")

    workspace.rollback()

    assert (tmp_path / "app.py").read_text() == "x = 1\n"
    assert not (tmp_path / "new_file.py").exists()
    assert workspace.status() == []


def test_rollback_requires_verified_baseline(tmp_path):
    workspace = make_repo(tmp_path)

    with pytest.raises(GitWorkspaceError):
        workspace.rollback()
