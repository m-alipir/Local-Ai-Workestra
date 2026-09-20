import subprocess

import pytest

from local_agent_orchestrator.services.diff_patch import (
    DiffPatchError,
    apply_unified_diff,
    extract_changed_files,
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


def commit_all(path):
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


def test_apply_unified_diff_modifies_existing_file(tmp_path):
    init_repo(tmp_path)

    (tmp_path / "app.py").write_text(
        "def greet(name):\n"
        "    return f\"Hello {name}\"\n"
    )

    commit_all(tmp_path)

    patch = (
        "diff --git a/app.py b/app.py\n"
        "index e9f6f43..12d7c6e 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,5 @@\n"
        " def greet(name):\n"
        "     return f\"Hello {name}\"\n"
        "+\n"
        "+def farewell(name):\n"
        "+    return f\"Goodbye {name}\"\n"
    )

    changed = apply_unified_diff(
        tmp_path,
        patch,
    )

    assert changed == ["app.py"]

    content = (tmp_path / "app.py").read_text()

    assert "def greet" in content
    assert "def farewell" in content


def test_apply_unified_diff_can_create_file(tmp_path):
    init_repo(tmp_path)

    patch = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "index 0000000..2c18f74\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1 @@\n"
        "+value = 1\n"
    )

    changed = apply_unified_diff(
        tmp_path,
        patch,
    )

    assert changed == ["new.py"]
    assert (tmp_path / "new.py").read_text() == "value = 1\n"


def test_invalid_patch_does_not_modify_workspace(tmp_path):
    init_repo(tmp_path)

    file = tmp_path / "app.py"
    file.write_text("value = 1\n")

    commit_all(tmp_path)

    patch = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 999\n"
        "+value = 2\n"
    )

    with pytest.raises(DiffPatchError):
        apply_unified_diff(
            tmp_path,
            patch,
        )

    assert file.read_text() == "value = 1\n"


def test_parent_traversal_is_blocked():
    patch = (
        "diff --git a/../secret.txt b/../secret.txt\n"
        "--- a/../secret.txt\n"
        "+++ b/../secret.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(
        DiffPatchError,
        match="Parent traversal",
    ):
        extract_changed_files(patch)


def test_grounded_existing_file_modification(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    patch = (
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    assert apply_unified_diff(
        tmp_path,
        patch,
        grounded_paths={"app.py"},
    ) == ["app.py"]


def test_ungrounded_existing_file_is_rejected_before_git_apply(tmp_path):
    init_repo(tmp_path)

    patch = (
        "diff --git a/missing.py b/missing.py\n"
        "--- a/missing.py\n"
        "+++ b/missing.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(DiffPatchError, match="missing.py"):
        apply_unified_diff(tmp_path, patch, grounded_paths=set())


def test_grounding_allows_legitimate_new_file(tmp_path):
    init_repo(tmp_path)

    patch = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1 @@\n"
        "+value = 1\n"
    )

    assert apply_unified_diff(
        tmp_path,
        patch,
        grounded_paths=set(),
    ) == ["new.py"]


def test_grounding_preserves_path_traversal_rejection():
    patch = (
        "diff --git a/../secret.txt b/../secret.txt\n"
        "--- a/../secret.txt\n"
        "+++ b/../secret.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    with pytest.raises(DiffPatchError, match="Parent traversal"):
        apply_unified_diff(".", patch, grounded_paths=set())


def test_grounded_rename_requires_both_paths(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "old.py").write_text("value = 1\n")
    commit_all(tmp_path)

    patch = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )

    assert apply_unified_diff(
        tmp_path,
        patch,
        grounded_paths={"old.py", "new.py"},
    ) == ["new.py"]


def test_grounded_delete_requires_existing_source_path(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "old.py").write_text("value = 1\n")
    commit_all(tmp_path)

    patch = (
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-value = 1\n"
    )

    assert apply_unified_diff(
        tmp_path,
        patch,
        grounded_paths={"old.py"},
    ) == ["old.py"]


def test_malformed_diff_path_header_is_rejected():
    patch = "diff --git missing-header\n--- a/app.py\n+++ b/app.py\n"

    with pytest.raises(DiffPatchError, match="Malformed diff path header"):
        extract_changed_files(patch)
