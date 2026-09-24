from unittest.mock import patch
import subprocess

from local_agent_orchestrator.models.scope import ScopeReview
from local_agent_orchestrator.services.scope_review import (
    review_unexpected_scope,
)


def test_scope_review_sends_only_unexpected_diff(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "web.js").write_text("old\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("value = 2\n")
    (tmp_path / "web.js").write_text("unexpected\n")

    review = ScopeReview(
        decision="PASS",
        reason="The integration change is required.",
        preserve_paths=["app.py", "web.js"],
    )
    with patch(
        "local_agent_orchestrator.services.scope_review.GptOssReviewer"
    ) as reviewer_type:
        reviewer_type.return_value.review_scope.return_value = review
        result = review_unexpected_scope(
            task="Update the service",
            workspace_root=tmp_path,
            changed_files=["app.py", "web.js"],
            primary_scope=["app.py"],
            discouraged_scope=["web.js"],
            forbidden_scope=[],
        )

    assert result == review
    prompt = reviewer_type.return_value.review_scope.call_args.kwargs
    assert prompt["changed_files"] == ["app.py", "web.js"]
    assert "unexpected" in prompt["diff_text"]
    assert "value = 2" not in prompt["diff_text"]


def test_scope_review_rejects_paths_outside_changed_files(tmp_path):
    (tmp_path / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    review = ScopeReview(
        decision="REVISE",
        reason="Too broad",
        remove_paths=["other.py"],
        instruction="Remove the unrelated change.",
    )
    with patch(
        "local_agent_orchestrator.services.scope_review.GptOssReviewer"
    ) as reviewer_type:
        reviewer_type.return_value.review_scope.return_value = review
        result = review_unexpected_scope(
            task="Update the service",
            workspace_root=tmp_path,
            changed_files=["app.py"],
            primary_scope=[],
            discouraged_scope=["app.py"],
            forbidden_scope=[],
        )

    assert result.decision == "FAIL_HARD"
    assert "outside the changed-file set" in result.reason
