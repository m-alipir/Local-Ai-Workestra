from unittest.mock import MagicMock, patch

import pytest

from local_agent_orchestrator.services.security import (
    _git_diff,
    parse_security_review,
    requires_security_review,
    run_security_review,
)
from local_agent_orchestrator.core.config import load_models


def test_security_trigger_detects_sensitive_task():
    assert requires_security_review(
        "Add JWT authentication to the API",
        ["src/auth.py"],
    ) is True


def test_security_trigger_ignores_simple_math_task():
    assert requires_security_review(
        "Add two numbers",
        ["calculator.py"],
    ) is False


def test_parse_security_review():
    review = parse_security_review(
        '{"findings":[{'
        '"severity":"high",'
        '"title":"Auth bypass",'
        '"description":"Missing authorization check",'
        '"recommendation":"Enforce ownership"'
        '}]}'
    )

    assert review.has_blocking_findings is True
    assert review.findings[0].severity == "high"


def test_run_security_review(tmp_path):
    (tmp_path / "auth.py").write_text("def auth(): pass\n")
    fake_reviewer = MagicMock()
    fake_reviewer.review.return_value.content = '{"findings":[]}'

    with (
        patch(
            "local_agent_orchestrator.services.security.SecurityReviewer",
            return_value=fake_reviewer,
        ) as reviewer_class,
        patch(
            "local_agent_orchestrator.services.security._git_diff",
            return_value="",
        ),
    ):
        result = run_security_review(
            task="Add API auth",
            changed_files=["auth.py"],
            workspace_root=tmp_path,
        )

    assert result.findings == []
    assert result.has_blocking_findings is False
    assert reviewer_class.call_args.kwargs["model"] == load_models().models["gpt_oss"]


def test_run_security_review_can_inspect_committed_revision(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n")
    fake_reviewer = MagicMock()
    fake_reviewer.review.return_value.content = '{"findings":[]}'

    with (
        patch(
            "local_agent_orchestrator.services.security.SecurityReviewer",
            return_value=fake_reviewer,
        ),
        patch(
            "local_agent_orchestrator.services.security._git_diff",
            return_value="committed diff",
        ) as git_diff,
    ):
        run_security_review(
            task="Review change",
            changed_files=["app.py"],
            workspace_root=tmp_path,
            revision="HEAD",
        )

    git_diff.assert_called_once_with(tmp_path, revision="HEAD")
    assert fake_reviewer.review.call_args.kwargs["diff_text"] == "committed diff"


def test_git_diff_failure_is_not_replaced_with_empty_review_evidence(tmp_path):
    failed = MagicMock(returncode=1, stdout="", stderr="git failed")

    with patch(
        "local_agent_orchestrator.services.security.subprocess.run",
        return_value=failed,
    ):
        with pytest.raises(RuntimeError, match="git failed"):
            _git_diff(tmp_path)
