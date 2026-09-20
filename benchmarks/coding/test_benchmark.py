import json
import hashlib
from pathlib import Path
from unittest.mock import patch

from local_agent_orchestrator.models.config import ModelConfig, ModelsConfig
from local_agent_orchestrator.services.edit_operations import EditOperationError

from .runner import CASES, _evidence, _failure_class, _workspace


def test_cases_cover_existing_edit_security_guard_and_new_file():
    assert len(CASES) == 3
    assert CASES[0].allowed_paths == ("src/names.py", "tests/test_names.py")
    assert CASES[1].allowed_paths == ("src/urls.py", "tests/test_urls.py")
    assert CASES[2].allowed_paths == (
        "src/identifiers.py",
        "tests/test_identifiers.py",
    )


def test_fixtures_are_clean_git_workspaces(tmp_path: Path):
    for case in CASES:
        root = _workspace(case, tmp_path)
        status = (root / ".git").exists()
        assert status


def test_failure_class_preserves_operation_categories():
    error = EditOperationError("no match", failure_class="no_match")

    assert _failure_class(error) == "no_match"


def test_workspace_fixture_has_no_external_generated_files(tmp_path: Path):
    root = _workspace(CASES[0], tmp_path)

    files = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )
    assert files == sorted(CASES[0].files)


def test_identical_fixture_evidence_has_identical_digest(tmp_path: Path):
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    first = _workspace(CASES[0], first_parent)
    second = _workspace(CASES[0], second_parent)

    first_digest = hashlib.sha256(
        _evidence(CASES[0], first).as_prompt().encode()
    ).hexdigest()
    second_digest = hashlib.sha256(
        _evidence(CASES[0], second).as_prompt().encode()
    ).hexdigest()

    assert first_digest == second_digest
