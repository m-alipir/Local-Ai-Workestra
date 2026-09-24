import subprocess

import pytest

from local_agent_orchestrator.models.plan import PlanTask
from local_agent_orchestrator.services.task_scope import (
    classify_changed_files,
    is_forbidden_path,
)


def test_primary_edit_is_normal_and_discouraged_edit_is_grey():
    classification = classify_changed_files(
        ["app/service.py", "app/main.py", "web/app.js"],
        primary_scope=["app/service.py"],
        discouraged_scope=["app/main.py"],
        forbidden_scope=[".git/"],
    )

    assert classification.primary == ("app/service.py",)
    assert classification.discouraged == ("app/main.py",)
    assert classification.unexpected == ("web/app.js",)
    assert classification.forbidden == ()


def test_builtin_forbidden_paths_are_hard_boundaries():
    assert is_forbidden_path(".git/config")
    assert is_forbidden_path(".env.production")
    assert is_forbidden_path(".env.test")
    assert is_forbidden_path("credentials.json")
    assert is_forbidden_path("config/client_secret.json")
    assert is_forbidden_path("credentials.ini")
    assert is_forbidden_path("production/app.py", ["production/"])
    assert not is_forbidden_path("src/app.py")


def test_legacy_file_boundaries_map_to_primary_scope():
    task = PlanTask(description="Implement", file_boundaries=["app/"])

    assert task.primary_scope == ["app/"]
    assert task.file_boundaries == ["app/"]


def test_scope_paths_remain_relative_and_safe():
    with pytest.raises(ValueError, match="safe relative paths"):
        PlanTask(description="Unsafe", forbidden_scope=["../outside"])
