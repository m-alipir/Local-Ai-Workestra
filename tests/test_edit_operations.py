import json
import subprocess

import pytest

from local_agent_orchestrator.services.edit_operations import (
    EditOperationError,
    apply_edit_operations,
    parse_edit_response,
)


def init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
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
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"],
        cwd=path,
        check=True,
    )


def response(*operations):
    return parse_edit_response(
        json.dumps({"operations": list(operations)})
    )


def test_grounded_existing_file_exact_replacement(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    changed = apply_edit_operations(
        tmp_path,
        response({
            "kind": "replace_exact",
            "path": "app.py",
            "old_text": "value = 1",
            "new_text": "value = 2",
        }),
        grounded_paths={"app.py"},
    )

    assert changed == ["app.py"]
    assert (tmp_path / "app.py").read_text() == "value = 2\n"


def test_nonexistent_existing_file_is_rejected(tmp_path):
    init_repo(tmp_path)
    (tmp_path / ".keep").write_text("\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="does not exist") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "missing.py",
                "old_text": "old",
                "new_text": "new",
            }),
            grounded_paths={"missing.py"},
        )

    assert error.value.failure_class == "ungrounded_path"


def test_existing_path_without_authoritative_evidence_is_rejected(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="not grounded") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            }),
        )

    assert error.value.failure_class == "ungrounded_path"


def test_legitimate_new_file_creation(tmp_path):
    init_repo(tmp_path)
    (tmp_path / ".keep").write_text("\n")
    commit_all(tmp_path)

    changed = apply_edit_operations(
        tmp_path,
        response({
            "kind": "create_file",
            "path": "new.py",
            "content": "value = 1\n",
        }),
    )

    assert changed == ["new.py"]
    assert (tmp_path / "new.py").read_text() == "value = 1\n"


def test_create_existing_path_is_rejected_as_path_conflict(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="already exists") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "create_file",
                "path": "app.py",
                "content": "value = 2\n",
            }),
        )

    assert error.value.failure_class == "path_conflict"


def test_retry_can_edit_file_created_by_prior_attempt(tmp_path):
    init_repo(tmp_path)
    (tmp_path / ".keep").write_text("\n")
    commit_all(tmp_path)

    apply_edit_operations(
        tmp_path,
        response({
            "kind": "create_file",
            "path": "new.py",
            "content": "value = 1\n",
        }),
    )

    changed = apply_edit_operations(
        tmp_path,
        response({
            "kind": "replace_exact",
            "path": "new.py",
            "old_text": "value = 1",
            "new_text": "value = 2",
        }),
        grounded_paths={"new.py"},
    )

    assert changed == ["new.py"]
    assert (tmp_path / "new.py").read_text() == "value = 2\n"


def test_path_traversal_is_rejected(tmp_path):
    init_repo(tmp_path)
    (tmp_path / ".keep").write_text("\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="Parent traversal") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "create_file",
                "path": "../outside.py",
                "content": "bad\n",
            }),
        )

    assert error.value.failure_class == "unsafe_path"


def test_delete_requires_grounded_existing_file(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "old.py").write_text("value = 1\n")
    commit_all(tmp_path)

    changed = apply_edit_operations(
        tmp_path,
        response({
            "kind": "delete_file",
            "path": "old.py",
        }),
        grounded_paths={"old.py"},
    )

    assert changed == ["old.py"]
    assert not (tmp_path / "old.py").exists()


def test_replace_requires_one_exact_match(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\nvalue = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="matched 2 times") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": "value = 1",
                "new_text": "value = 2",
            }),
            grounded_paths={"app.py"},
        )

    assert error.value.failure_class == "ambiguous_match"


def test_replace_with_no_match_is_classified(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="matched zero") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": "missing",
                "new_text": "value = 2",
            }),
            grounded_paths={"app.py"},
        )

    assert error.value.failure_class == "no_match"


def test_no_op_replacement_is_classified(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="no workspace changes") as error:
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": "value = 1",
                "new_text": "value = 1",
            }),
            grounded_paths={"app.py"},
        )

    assert error.value.failure_class == "no_op"


def test_replace_rejects_overlapping_exact_matches(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("aaa\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="matched 2 times"):
        apply_edit_operations(
            tmp_path,
            response({
                "kind": "replace_exact",
                "path": "app.py",
                "old_text": "aa",
                "new_text": "bb",
            }),
            grounded_paths={"app.py"},
        )


def test_malformed_operation_response_is_rejected():
    with pytest.raises(EditOperationError, match="trailing text") as error:
        parse_edit_response(
            '{"operations": []}\nnot-json'
        )

    assert error.value.failure_class == "invalid_schema"

    with pytest.raises(EditOperationError, match="old_text") as error:
        parse_edit_response(
            json.dumps({
                "operations": [{
                    "kind": "replace_exact",
                    "path": "app.py",
                    "old_text": "",
                    "new_text": "new",
                }]
            })
        )

    assert error.value.failure_class == "empty_old_text"


def test_operation_path_aliases_are_rejected(tmp_path):
    init_repo(tmp_path)
    (tmp_path / "app.py").write_text("value = 1\n")
    commit_all(tmp_path)

    with pytest.raises(EditOperationError, match="same path"):
        apply_edit_operations(
            tmp_path,
            response(
                {
                    "kind": "replace_exact",
                    "path": "app.py",
                    "old_text": "value = 1",
                    "new_text": "value = 2",
                },
                {
                    "kind": "replace_exact",
                    "path": "./app.py",
                    "old_text": "value = 1",
                    "new_text": "value = 3",
                },
            ),
            grounded_paths={"app.py", "./app.py"},
        )
