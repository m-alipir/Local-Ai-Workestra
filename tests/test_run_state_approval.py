import pytest

import json

from local_agent_orchestrator.models.task import TaskStatus
from local_agent_orchestrator.services.run_state import (
    RunStateManager,
)


def test_task_can_wait_for_approval(tmp_path):
    manager = RunStateManager(tmp_path / "runs")

    state = manager.create_run(
        "Deploy release"
    )

    task = manager.add_task(
        state,
        "Deploy production",
    )

    manager.mark_waiting_for_approval(
        state,
        task.id,
    )

    loaded = manager.load(
        state.run_id
    )

    loaded_task = manager.get_task(
        loaded,
        task.id,
    )

    assert loaded.status == TaskStatus.WAITING_FOR_APPROVAL
    assert loaded.current_task == task.id
    assert loaded_task.status == TaskStatus.WAITING_FOR_APPROVAL
    assert loaded_task.approval_granted is False


def test_waiting_task_can_be_approved(tmp_path):
    manager = RunStateManager(tmp_path / "runs")

    state = manager.create_run(
        "Deploy release"
    )

    task = manager.add_task(
        state,
        "Deploy production",
    )

    manager.mark_waiting_for_approval(
        state,
        task.id,
    )

    manager.approve_task(
        state,
        task.id,
    )

    loaded = manager.load(
        state.run_id
    )

    loaded_task = manager.get_task(
        loaded,
        task.id,
    )

    assert loaded.status == TaskStatus.PENDING
    assert loaded_task.status == TaskStatus.PENDING
    assert loaded_task.approval_granted is True

    events = [
        json.loads(line)
        for line in (
            tmp_path / "runs" / state.run_id / "trajectory.jsonl"
        ).read_text().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "approval_requested",
        "approval_granted",
    ]


def test_non_waiting_task_cannot_be_approved(tmp_path):
    manager = RunStateManager(tmp_path / "runs")

    state = manager.create_run(
        "Feature"
    )

    task = manager.add_task(
        state,
        "Implement feature",
    )

    with pytest.raises(
        RuntimeError,
        match="not waiting",
    ):
        manager.approve_task(
            state,
            task.id,
        )
