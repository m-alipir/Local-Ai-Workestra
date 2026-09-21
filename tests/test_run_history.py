from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.run_history import (
    RunHistory,
)


def _write_run(runs_dir, run_id: str, status: TaskStatus, updated_at: datetime):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "request": "history test",
                "status": status.value,
                "updated_at": updated_at.isoformat(),
                "tasks": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "trajectory.jsonl").write_text("event\n", encoding="utf-8")


def test_archive_moves_only_terminal_run_artifacts(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    target_repo = tmp_path / "target-repo"
    target_repo.mkdir()
    (target_repo / "agent-branch-marker").write_text("keep", encoding="utf-8")
    old = datetime.now(timezone.utc) - timedelta(days=30)
    _write_run(runs_dir, "run-1", TaskStatus.FAILED, old)

    archived = RunHistory(runs_dir).archive(
        "run-1",
        before=datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert archived == runs_dir / ".archive" / "run-1"
    assert not (runs_dir / "run-1").exists()
    assert (archived / "trajectory.jsonl").read_text() == "event\n"
    assert (target_repo / "agent-branch-marker").read_text() == "keep"


def test_cleanup_rejects_active_or_recent_runs(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    now = datetime.now(timezone.utc)
    _write_run(runs_dir, "active", TaskStatus.RUNNING, now - timedelta(days=30))
    _write_run(runs_dir, "recent", TaskStatus.PASSED, now)
    history = RunHistory(runs_dir)

    with pytest.raises(ValueError, match="terminal"):
        history.archive("active")
    with pytest.raises(ValueError, match="old enough"):
        history.delete("recent", before=now - timedelta(days=1))


def test_delete_removes_selected_run_but_not_other_control_or_target_data(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    target_repo = tmp_path / "repo"
    target_repo.mkdir()
    (target_repo / "source.py").write_text("keep", encoding="utf-8")
    old = datetime.now(timezone.utc) - timedelta(days=30)
    _write_run(runs_dir, "remove", TaskStatus.PASSED, old)
    _write_run(runs_dir, "keep", TaskStatus.PASSED, old)

    RunHistory(runs_dir).delete(
        "remove",
        before=datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert not (runs_dir / "remove").exists()
    assert (runs_dir / "keep" / "state.json").exists()
    assert (target_repo / "source.py").read_text() == "keep"


def test_history_rejects_traversal_and_symlink_targets(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "state.json").write_text("{}", encoding="utf-8")
    (runs_dir / "linked").symlink_to(outside, target_is_directory=True)
    history = RunHistory(runs_dir)

    with pytest.raises(ValueError, match="run id"):
        history.delete("../outside")
    with pytest.raises(ValueError, match="symlink"):
        history.delete("linked")
